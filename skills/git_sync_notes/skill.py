#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

MAX_OUTPUT = 8000
UNMERGED_PREFIXES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
DEFAULT_NOTES_REPO_PATH = "__NOTES_REPO_PATH__"
NOTE_FILE_RE = re.compile(r"^notes/\d{4}/\d{4}-\d{2}/\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LEGACY_SHORTID_RE = re.compile(r".*-[0-9a-f]{8}$")


def truncate(text):
    if not text:
        return ""
    if len(text) <= MAX_OUTPUT:
        return text
    return text[: MAX_OUTPUT - 12] + "...truncated"


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
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")
    return value


def run_git(args, cwd, env, stdout_parts, stderr_parts):
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.stdout:
        stdout_parts.append(proc.stdout)
    if proc.stderr:
        stderr_parts.append(proc.stderr)
    return proc


def detect_conflict(output):
    lowered = output.lower()
    markers = [
        "conflict",
        "fix conflicts",
        "resolve all conflicts",
        "after resolving the conflicts",
        "could not apply",
    ]
    return any(marker in lowered for marker in markers)


def has_unmerged(porcelain):
    for line in porcelain.splitlines():
        if len(line) < 2:
            continue
        status = line[:2]
        if status in UNMERGED_PREFIXES or "U" in status:
            return True
    return False


def get_current_branch(cwd, env, stdout_parts, stderr_parts):
    proc = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd, env, stdout_parts, stderr_parts)
    if proc.returncode != 0:
        return None
    branch = proc.stdout.strip()
    if branch == "HEAD" or not branch:
        return None
    return branch


def build_commit_message():
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"notes: sync {timestamp}"


def parse_front_matter(lines):
    if not lines or lines[0].strip() != "---":
        return {}, 0, "missing opening front matter delimiter"
    fm = {}
    end = -1
    for idx in range(1, min(len(lines), 120)):
        line = lines[idx].rstrip("\n")
        if line.strip() == "---":
            end = idx
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fm[key.strip()] = value.strip().strip('"').strip("'")
    if end == -1:
        return {}, 0, "missing closing front matter delimiter"
    return fm, end + 1, ""


def first_h1(lines, start_idx):
    for idx in range(start_idx, len(lines)):
        stripped = lines[idx].strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            return stripped[2:].strip()
        return None
    return None


def validate_note_file(abs_path, rel_path):
    errors = []
    try:
        with open(abs_path, "r", encoding="utf-8") as handle:
            content = handle.read()
    except UnicodeDecodeError:
        return [f"{rel_path}: file is not valid UTF-8"]

    lines = content.splitlines()

    if not NOTE_FILE_RE.match(rel_path.replace("\\", "/")):
        errors.append(
            f"{rel_path}: invalid filename/path; expected notes/YYYY/YYYY-MM/YYYY-MM-DD-topic-slug.md"
        )
    else:
        stem = os.path.basename(rel_path).replace(".md", "")
        if LEGACY_SHORTID_RE.match(stem):
            errors.append(f"{rel_path}: filename appears to include a legacy shortid suffix")

    fm, body_start, fm_error = parse_front_matter(lines)
    if fm_error:
        errors.append(f"{rel_path}: {fm_error}")
        return errors

    for key in ("title", "date", "project", "topic"):
        if not fm.get(key):
            errors.append(f"{rel_path}: missing required front matter field '{key}'")

    note_date = fm.get("date", "")
    if note_date and not DATE_RE.match(note_date):
        errors.append(f"{rel_path}: front matter date must be YYYY-MM-DD")

    base_name = os.path.basename(rel_path).replace(".md", "")
    if note_date and DATE_RE.match(note_date) and not base_name.startswith(f"{note_date}-"):
        errors.append(f"{rel_path}: filename date prefix must match front matter date")

    h1 = first_h1(lines, body_start)
    if not h1:
        errors.append(f"{rel_path}: first non-empty heading must be an H1")
    elif fm.get("title") and h1 != fm.get("title"):
        errors.append(f"{rel_path}: first H1 must exactly match front matter title")

    return errors


def validate_staged_notes(repo_path, staged):
    issues = []
    for rel_path in staged:
        rel_norm = rel_path.replace("\\", "/")
        if not rel_norm.startswith("notes/"):
            continue
        if not rel_norm.endswith(".md"):
            continue
        if not re.match(r"^notes/\d{4}/\d{4}-\d{2}/", rel_norm):
            continue
        abs_path = os.path.join(repo_path, rel_path)
        if not os.path.isfile(abs_path):
            continue
        issues.extend(validate_note_file(abs_path, rel_norm))
    return issues


def process(data):
    if not isinstance(data, dict):
        raise ValueError("Input JSON must be an object")

    repo_path = ensure_string(data.get("repo_path"), "repo_path")
    commit_message = ensure_string(data.get("commit_message"), "commit_message")
    author_name = ensure_string(data.get("author_name"), "author_name")
    author_email = ensure_string(data.get("author_email"), "author_email")
    remote = ensure_string(data.get("remote"), "remote") or "origin"
    branch = ensure_string(data.get("branch"), "branch")
    add_paths = ensure_string_list(data.get("add_paths"), "add_paths")
    allow_empty_commit = data.get("allow_empty_commit", False)
    if not isinstance(allow_empty_commit, bool):
        raise ValueError("allow_empty_commit must be a boolean")

    if not repo_path:
        repo_path = DEFAULT_NOTES_REPO_PATH
    if repo_path == DEFAULT_NOTES_REPO_PATH:
        raise ValueError(
            "repo_path is masked. Replace DEFAULT_NOTES_REPO_PATH in skill.py or provide repo_path in input."
        )
    if not os.path.isdir(repo_path):
        raise ValueError("repo_path does not exist or is not a directory")
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        raise ValueError("repo_path is not a git repository (missing .git)")

    if add_paths is None or len(add_paths) == 0:
        add_paths = ["notes/"]

    env = os.environ.copy()
    if author_name:
        env["GIT_AUTHOR_NAME"] = author_name
        env["GIT_COMMITTER_NAME"] = author_name
    if author_email:
        env["GIT_AUTHOR_EMAIL"] = author_email
        env["GIT_COMMITTER_EMAIL"] = author_email

    stdout_parts = []
    stderr_parts = []
    actions = []

    proc = run_git(["status", "--porcelain"], repo_path, env, stdout_parts, stderr_parts)
    if proc.returncode != 0:
        raise RuntimeError("git status failed")

    if branch is None:
        branch = get_current_branch(repo_path, env, stdout_parts, stderr_parts)

    pull_args = ["pull", "--rebase", remote]
    if branch:
        pull_args.append(branch)
    proc = run_git(pull_args, repo_path, env, stdout_parts, stderr_parts)
    if proc.returncode != 0:
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if detect_conflict(output):
            raise RuntimeError("Pull failed due to conflicts. Resolve conflicts and rerun.")
        raise RuntimeError("git pull --rebase failed")
    actions.append("pulled")

    proc = run_git(["status", "--porcelain"], repo_path, env, stdout_parts, stderr_parts)
    if proc.returncode != 0:
        raise RuntimeError("git status failed after pull")
    if has_unmerged(proc.stdout):
        raise RuntimeError("Unmerged paths detected after pull. Resolve conflicts and rerun.")

    proc = run_git(["add", *add_paths], repo_path, env, stdout_parts, stderr_parts)
    if proc.returncode != 0:
        raise RuntimeError("git add failed")
    actions.append("added")

    proc = run_git(["diff", "--cached", "--name-only"], repo_path, env, stdout_parts, stderr_parts)
    if proc.returncode != 0:
        raise RuntimeError("git diff --cached failed")
    staged = [line for line in proc.stdout.splitlines() if line.strip()]

    validation_issues = validate_staged_notes(repo_path, staged)
    if validation_issues:
        joined = "\n".join(validation_issues[:20])
        raise RuntimeError(f"Note validation failed:\n{joined}")

    if not staged and not allow_empty_commit:
        return {
            "ok": True,
            "actions": ["pulled"],
            "commit_hash": "",
            "stdout": truncate("".join(stdout_parts)),
            "stderr": truncate("".join(stderr_parts)),
        }

    if not commit_message:
        commit_message = build_commit_message()

    commit_args = ["commit", "-m", commit_message]
    if allow_empty_commit and not staged:
        commit_args.insert(1, "--allow-empty")
    proc = run_git(commit_args, repo_path, env, stdout_parts, stderr_parts)
    if proc.returncode != 0:
        raise RuntimeError("git commit failed")
    actions.append("committed")

    proc = run_git(["rev-parse", "HEAD"], repo_path, env, stdout_parts, stderr_parts)
    commit_hash = proc.stdout.strip() if proc.returncode == 0 else ""

    if branch:
        push_args = ["push", remote, branch]
    else:
        push_args = ["push"]
    proc = run_git(push_args, repo_path, env, stdout_parts, stderr_parts)
    if proc.returncode != 0:
        raise RuntimeError("git push failed")
    actions.append("pushed")

    return {
        "ok": True,
        "actions": actions,
        "commit_hash": commit_hash,
        "stdout": truncate("".join(stdout_parts)),
        "stderr": truncate("".join(stderr_parts)),
    }


def main():
    parser = argparse.ArgumentParser(description="Sync a notes git repo with pull/add/commit/push.")
    parser.add_argument("--input", help="Path to input JSON. If omitted, read from stdin.")
    args = parser.parse_args()

    try:
        data = read_input(args.input)
        result = process(data)
    except Exception as exc:
        result = {
            "ok": False,
            "actions": [],
            "commit_hash": "",
            "stdout": "",
            "stderr": "",
            "error": str(exc),
        }

    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()






