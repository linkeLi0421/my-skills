---
name: git_sync_notes
description: Safely sync a notes Git repository with GitHub by pulling with rebase, staging note changes, committing with a generated message, and pushing. Use after note-writing skills to automate repo sync without manual git steps.
---

# Git Sync Notes

## Run the skill
- `python -m skills.git_sync_notes.skill < input.json`

## Behavior
- Verify the repo path and `.git` directory exist.
- Pull with rebase, stage changes (default `notes/`), commit, and push.
- Return structured JSON with actions performed and truncated git output.
- Fail fast with clear errors on conflicts or git failures.
- A masked default repo path is built in. Replace `DEFAULT_NOTES_REPO_PATH` in `skill.py` after installing, or pass `repo_path` in input.

## Input/Output
- Read JSON from stdin by default.
- Write JSON to stdout with `ok`, `actions`, and optional `commit_hash`.
- See `config.schema.json` for the input schema.
