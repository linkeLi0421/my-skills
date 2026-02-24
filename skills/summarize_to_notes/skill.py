#!/usr/bin/env python3
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

DEFAULT_MAX_EXCERPT_LINES = 8
DEFAULT_NOTES_REPO_PATH = "__NOTES_REPO_PATH__"
MAX_TAGS = 12
MAX_LINE_LEN = 300

FILE_LINE_RE = re.compile(r"([A-Za-z0-9_./\\-]+):(\d+)(?::(\d+))?")
URL_RE = re.compile(r"https?://\S+")
ERROR_RE = re.compile(r"\b(error|fatal|exception|traceback)\b", re.IGNORECASE)
WARNING_RE = re.compile(r"\bwarning\b", re.IGNORECASE)


def read_input(path):
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    else:
        raw = sys.stdin.read()
    if not raw.strip():
        raise ValueError("No input JSON provided")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON input: {exc}")


def ensure_string(value, name, required=False):
    if value is None:
        if required:
            raise ValueError(f"{name} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def ensure_string_list(value, name):
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")
    return value


def resolve_timezone(tz_name):
    if tz_name:
        if ZoneInfo is None:
            raise ValueError("timezone provided but zoneinfo is not available")
        try:
            return ZoneInfo(tz_name)
        except Exception:
            raise ValueError(f"Invalid timezone: {tz_name}")
    return dt.datetime.now().astimezone().tzinfo


def resolve_date(date_str, tzinfo):
    if date_str:
        try:
            return dt.date.fromisoformat(date_str)
        except ValueError:
            raise ValueError("date must be in YYYY-MM-DD format")
    return dt.datetime.now(tzinfo).date()


def slugify(value, max_len=40):
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    if not value:
        value = "note"
    if len(value) > max_len:
        value = value[:max_len].rstrip("-")
    return value


def normalize_tag(tag):
    tag = tag.strip().lower()
    tag = re.sub(r"\s+", "-", tag)
    tag = re.sub(r"[^a-z0-9-]", "", tag)
    tag = re.sub(r"-{2,}", "-", tag).strip("-")
    return tag


def dedupe_preserve(items):
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def sanitize_line(line):
    line = line.rstrip("\n")
    if len(line) > MAX_LINE_LEN:
        return line[: MAX_LINE_LEN - 3] + "..."
    return line


def score_line(line):
    score = 0
    lower = line.lower()
    if "error" in lower:
        score += 3
    if "fatal" in lower:
        score += 3
    if "exception" in lower:
        score += 2
    if "traceback" in lower:
        score += 2
    if "warning" in lower:
        score += 1
    if "implicit declaration" in lower:
        score += 2
    if "redefinition" in lower:
        score += 2
    if FILE_LINE_RE.search(line):
        score += 2
    return score


def select_evidence(lines, max_lines):
    nonempty = [line for line in lines if line.strip()]
    scored = []
    for idx, line in enumerate(nonempty):
        score = score_line(line)
        if score > 0:
            scored.append((score, idx, line))
    if scored:
        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = scored[:max_lines]
        selected.sort(key=lambda item: item[1])
        lines_out = [item[2] for item in selected]
    else:
        lines_out = nonempty[:max_lines]
    lines_out = dedupe_preserve(lines_out)
    if len(lines_out) < 3 and len(nonempty) > len(lines_out):
        for line in nonempty:
            if line in lines_out:
                continue
            lines_out.append(line)
            if len(lines_out) >= min(3, max_lines, len(nonempty)):
                break
    lines_out = [sanitize_line(line) for line in lines_out[:max_lines]]
    return lines_out


def extract_file_refs(lines):
    refs = []
    for line in lines:
        match = FILE_LINE_RE.search(line)
        if match:
            path = match.group(1)
            lineno = match.group(2)
            col = match.group(3)
            ref = f"{path}:{lineno}" + (f":{col}" if col else "")
            refs.append(ref)
    return dedupe_preserve(refs)


def clean_title_from_line(line):
    original = line.strip()
    cleaned = re.sub(r"^\[?\d{4}-\d{2}-\d{2}[^\]]*\]?\s*", "", original)
    cleaned = re.sub(r"^(error|fatal|exception|warning)[:\s-]+", "", cleaned, flags=re.IGNORECASE)
    error_match = re.search(r"\berror\b\s*[:\-]?\s*(.+)", cleaned, re.IGNORECASE)
    if error_match and error_match.group(1).strip():
        cleaned = error_match.group(1).strip()
    cleaned = cleaned.strip()
    if not cleaned:
        cleaned = original
    if len(cleaned) > 120:
        cleaned = cleaned[:117] + "..."
    return cleaned


def infer_title(lines, meta):
    for line in lines:
        if ERROR_RE.search(line) or WARNING_RE.search(line) or "implicit declaration" in line.lower() or "redefinition" in line.lower():
            return clean_title_from_line(line)
    topic = meta.get("topic") if isinstance(meta, dict) else None
    project = meta.get("project") if isinstance(meta, dict) else None
    if topic and project:
        return f"{project}: {topic}"
    if topic:
        return topic
    for line in lines:
        if line.strip():
            return clean_title_from_line(line)
    if project:
        return project
    return "Notes summary"


def build_tags(text, meta):
    tags = []
    if isinstance(meta, dict):
        tags.extend(meta.get("tags") or [])
    text_lower = text.lower()
    if "implicit declaration" in text_lower:
        tags.extend(["c99", "implicit-declaration"])
    if "redefinition" in text_lower:
        tags.append("redefinition")
    if "/src/htslib" in text_lower:
        tags.append("htslib")
    normalized = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        norm = normalize_tag(tag)
        if norm:
            normalized.append(norm)
    normalized = dedupe_preserve(normalized)
    return normalized[:MAX_TAGS]


def build_tldr(title, meta, file_refs, evidence_count):
    bullets = []
    if title:
        bullets.append(f"Main issue: {title}.")
    project = meta.get("project") if isinstance(meta, dict) else None
    topic = meta.get("topic") if isinstance(meta, dict) else None
    if project or topic:
        context = " / ".join([item for item in [project, topic] if item])
        bullets.append(f"Context: {context}.")
    if file_refs:
        bullets.append(f"Likely location: {file_refs[0]}.")
    if evidence_count:
        bullets.append(f"Evidence lines captured: {evidence_count}.")
    if len(bullets) < 3:
        bullets.append("Next step: review the evidence and reproduce the issue with a minimal case.")
    return bullets[:6]


def build_key_findings(evidence_lines, meta, file_refs):
    findings = []
    for line in evidence_lines:
        lower = line.lower()
        if "implicit declaration" in lower:
            findings.append("Implicit declaration detected in output.")
            continue
        if "redefinition" in lower:
            findings.append("Redefinition reported in output.")
            continue
        if ERROR_RE.search(line):
            findings.append(f"Error: {clean_title_from_line(line)}")
            continue
        if WARNING_RE.search(line):
            findings.append(f"Warning: {clean_title_from_line(line)}")
            continue
        if FILE_LINE_RE.search(line):
            findings.append(f"Location referenced: {line.strip()}")
    if file_refs:
        findings.append(f"File references include: {', '.join(file_refs[:3])}")
    files = meta.get("files") if isinstance(meta, dict) else None
    functions = meta.get("functions") if isinstance(meta, dict) else None
    if files:
        findings.append(f"Files mentioned: {', '.join(files[:5])}")
    if functions:
        findings.append(f"Functions mentioned: {', '.join(functions[:5])}")
    findings = dedupe_preserve(findings)
    if not findings:
        findings.append("No explicit error lines found; review excerpts for context.")
    return findings[:5]


def build_next_steps(text, file_refs, meta):
    steps = []
    text_lower = text.lower()
    if "implicit declaration" in text_lower:
        steps.append("Verify C99 headers or missing prototypes for implicit declaration errors.")
    if "redefinition" in text_lower:
        steps.append("Search for duplicate definitions or conflicting headers causing redefinition.")
    if file_refs:
        steps.append(f"Inspect {file_refs[0]} around the referenced line.")
    files = meta.get("files") if isinstance(meta, dict) else None
    if files:
        steps.append(f"Review related files: {', '.join(files[:3])}.")
    if not steps:
        steps.append("Reproduce the issue with a minimal input and capture a short log excerpt.")
    return steps[:5]


def build_links(text, meta):
    links = []
    if isinstance(meta, dict):
        links.extend(meta.get("links") or [])
    links.extend(URL_RE.findall(text))
    cleaned = []
    for link in links:
        if not isinstance(link, str):
            continue
        cleaned.append(link.strip())
    cleaned = dedupe_preserve(cleaned)
    return cleaned[:8]


def estimate_confidence(evidence_lines):
    if len(evidence_lines) >= 4:
        return "high"
    if len(evidence_lines) <= 1:
        return "low"
    return "medium"


def yaml_safe(value):
    if value is None:
        return "general"
    value = str(value)
    if re.match(r"^[A-Za-z0-9._/-]+$", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', "\\\"")
    return f'"{escaped}"'


def yaml_inline_list(items):
    if not items:
        return "[]"
    return "[" + ", ".join(items) + "]"


def build_summary(title, meta, evidence_count):
    parts = []
    if title:
        parts.append(f"Main issue: {title}.")
    project = meta.get("project") if isinstance(meta, dict) else None
    topic = meta.get("topic") if isinstance(meta, dict) else None
    if project or topic:
        context = " / ".join([item for item in [project, topic] if item])
        parts.append(f"Context: {context}.")
    if evidence_count:
        parts.append(f"Evidence includes {evidence_count} key lines.")
    return " ".join(parts[:3]) if parts else "Summary not available."


def render_note(note_id, date_str, project, topic, tags, source, confidence, title, tldr, findings, evidence, next_steps, links):
    lines = [
        "---",
        f"id: {note_id}",
        f"date: {date_str}",
        f"project: {yaml_safe(project)}",
        f"topic: {yaml_safe(topic)}",
        f"tags: {yaml_inline_list(tags)}",
        f"source: {yaml_safe(source)}",
        f"confidence: {confidence}",
        "---",
        f"# {title}",
        "",
        "## TL;DR",
    ]
    for bullet in tldr:
        lines.append(f"- {bullet}")
    lines.extend(["", "## Key findings"])
    for bullet in findings:
        lines.append(f"- {bullet}")
    lines.extend(["", "## Evidence (excerpts)"])
    if evidence:
        for line in evidence:
            lines.append(f"- {line}")
    else:
        lines.append("- (no excerpts found)")
    lines.extend(["", "## Next steps"])
    for bullet in next_steps:
        lines.append(f"- {bullet}")
    lines.extend(["", "## Links / References"])
    if links:
        for link in links:
            lines.append(f"- {link}")
    else:
        lines.append("- (none)")
    lines.append("")
    return "\n".join(lines)


def process(data):
    if not isinstance(data, dict):
        raise ValueError("Input JSON must be an object")
    text = ensure_string(data.get("text"), "text", required=True)
    notes_repo_path = ensure_string(data.get("notes_repo_path"), "notes_repo_path")
    meta = data.get("meta") or {}
    if not isinstance(meta, dict):
        raise ValueError("meta must be an object")
    meta = dict(meta)
    meta["project"] = ensure_string(meta.get("project"), "meta.project")
    meta["topic"] = ensure_string(meta.get("topic"), "meta.topic")
    meta["source"] = ensure_string(meta.get("source"), "meta.source")
    meta["tags"] = ensure_string_list(meta.get("tags"), "meta.tags")
    meta["files"] = ensure_string_list(meta.get("files"), "meta.files")
    meta["functions"] = ensure_string_list(meta.get("functions"), "meta.functions")
    meta["links"] = ensure_string_list(meta.get("links"), "meta.links")

    date_str = ensure_string(data.get("date"), "date")
    tz_name = ensure_string(data.get("timezone"), "timezone")
    slug_hint = ensure_string(data.get("slug_hint"), "slug_hint")
    max_excerpt_lines = data.get("max_excerpt_lines", DEFAULT_MAX_EXCERPT_LINES)
    if not isinstance(max_excerpt_lines, int) or max_excerpt_lines <= 0:
        raise ValueError("max_excerpt_lines must be a positive integer")

    if not notes_repo_path:
        notes_repo_path = DEFAULT_NOTES_REPO_PATH
    if notes_repo_path == DEFAULT_NOTES_REPO_PATH:
        raise ValueError(
            "notes_repo_path is masked. Replace DEFAULT_NOTES_REPO_PATH in skill.py or provide notes_repo_path in input."
        )
    if not os.path.isdir(notes_repo_path):
        raise ValueError("notes_repo_path does not exist or is not a directory")

    tzinfo = resolve_timezone(tz_name)
    date_value = resolve_date(date_str, tzinfo)
    date_str = date_value.isoformat()

    lines = [line.rstrip("\n") for line in text.splitlines()]
    evidence_lines = select_evidence(lines, max_excerpt_lines)
    file_refs = extract_file_refs(lines)

    title = infer_title(lines, meta)

    slug_basis = None
    project = meta.get("project") or "general"
    topic = meta.get("topic") or "general"
    if meta.get("project") or meta.get("topic"):
        slug_basis = " ".join([item for item in [meta.get("project"), meta.get("topic")] if item])
    elif slug_hint:
        slug_basis = slug_hint
    else:
        slug_basis = title
    slug = slugify(slug_basis)

    shortid_seed = f"{text}\n{date_str}"
    shortid = hashlib.sha1(shortid_seed.encode("utf-8")).hexdigest()[:8]
    note_id = f"{date_str}-{slug}-{shortid}"

    tags = build_tags(text, meta)

    tldr = build_tldr(title, meta, file_refs, len(evidence_lines))
    findings = build_key_findings(evidence_lines, meta, file_refs)
    next_steps = build_next_steps(text, file_refs, meta)
    links = build_links(text, meta)
    source = meta.get("source") or "chat"
    confidence = estimate_confidence(evidence_lines)
    summary = build_summary(title, meta, len(evidence_lines))

    year = date_str[:4]
    year_month = date_str[:7]
    filename = f"{date_str}-{slug}-{shortid}.md"
    note_path = os.path.join(notes_repo_path, "notes", year, year_month, filename)
    os.makedirs(os.path.dirname(note_path), exist_ok=True)

    note_content = render_note(
        note_id=note_id,
        date_str=date_str,
        project=project,
        topic=topic,
        tags=tags,
        source=source,
        confidence=confidence,
        title=title,
        tldr=tldr,
        findings=findings,
        evidence=evidence_lines,
        next_steps=next_steps,
        links=links,
    )

    with open(note_path, "w", encoding="utf-8") as handle:
        handle.write(note_content)

    return {
        "ok": True,
        "note_path": os.path.abspath(note_path),
        "note_id": note_id,
        "title": title,
        "tags": tags,
        "summary": summary,
    }


def main():
    parser = argparse.ArgumentParser(description="Summarize raw text into a structured Markdown note.")
    parser.add_argument("--input", help="Path to input JSON. If omitted, read from stdin.")
    args = parser.parse_args()

    try:
        data = read_input(args.input)
        result = process(data)
    except Exception as exc:
        result = {
            "ok": False,
            "note_path": "",
            "note_id": "",
            "title": "",
            "tags": [],
            "summary": "",
            "error": str(exc),
        }

    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
