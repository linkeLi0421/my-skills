---
name: summarize_to_notes
description: Summarize raw text (chat transcripts, build logs, code snippets) into structured Markdown notes with YAML front matter and write them to a local notes git repo. Use when you need deterministic, local summarization and note creation from unstructured text.
---

# Summarize to Notes

## Run the skill
- `python -m skills.summarize_to_notes.skill < input.json`
- `python skills/summarize_to_notes/skill.py --input input.json`

## Input and output
- Accept JSON input from stdin (default) or `--input` file.
- Write a Markdown note into the notes repo and return JSON status to stdout.
- See `config.schema.json` for the expected input fields.

## Behavior
- Build a note path as `{notes_repo_path}/notes/YYYY/YYYY-MM/YYYY-MM-DD-<topic-slug>.md`.
- Derive `<topic-slug>` from `meta.topic`, else `slug_hint`, else the inferred title.
- `auto` mode defaults to summary; use `mode=document` to store a full Markdown body.
- Extract key error/warning lines and file:line patterns for evidence.
- Generate tags using simple heuristics and de-duplicate to a max of 12.
- Write required front matter fields: `title`, `date`, `project`, `topic`.
- Reject likely mojibake/garbled input to avoid writing corrupted notes.
- Fail gracefully with `ok=false` if the notes repo path is missing or input is invalid.
- A masked default repo path is built in. Replace `DEFAULT_NOTES_REPO_PATH` in `skill.py` after installing, or pass `notes_repo_path` in input.
