# My Codex Skills

This repo stores my Codex skills so I can install them into a new agent easily.

## Layout
- `skills/` — each skill lives in its own folder and must contain a `SKILL.md` at the root of that folder.
- `catalog.yaml` — a lightweight index of skills in this repo (optional but handy).

## Add a skill
1. Create a new folder under `skills/`.
2. Add a `SKILL.md` with the instructions.
3. (Optional) Add supporting files like `scripts/`, `assets/`, or `references/`.
4. Register it in `catalog.yaml`.

## Install a skill into a new agent
- **Manual:** copy the skill folder into `$CODEX_HOME/skills`.
- **Using the skill-installer skill:** install from this repo path when prompted.
