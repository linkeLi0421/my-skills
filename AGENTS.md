# AGENTS

This repo contains skills under `skills/`. Some agents only clone/download the repo and stop. That is not enough. A skill must be placed where your agent looks for skills (or you must add this repo's `skills/` directory to the agent's search path if it supports that).

## Manual install (always works)
1. Find your agent's skills directory (check its settings or docs; search for "skills", "extensions", or "plugins").
2. Copy the specific skill folder you want from this repo, e.g. `skills/<skill-name>`, into `<skills-dir>/<skill-name>`. If your agent supports adding a skills search path, you can add this repo's `skills/` directory instead of copying.
3. Verify the destination folder contains `SKILL.md` at its root.
4. Restart or refresh the agent so it reloads skills.

## If you have a skill installer
You can use a skill-installer tool to install from this repo path. If the installer only downloads/clones the repo, you still must copy the skill folder into your agent's skills directory (or add the repo's `skills/` directory as a search path) as described above.

## Notes
- Copy only the skill folder(s), not the entire repo.
- `catalog.yaml` is just an index for this repo and does not need to be copied.
