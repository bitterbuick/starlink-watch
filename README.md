# Starlink Watch (Cloud Automation)

- Runs hourly in GitHub Actions; emits only at **09:00** and **17:00 PT**.
- Writes `Starlink Watch/Events/<timestamp> — Starlink Daily Digest.md`
- Appends bullets to `Starlink Watch/Archive/*.md`

## Setup
1) Repo → Settings → Secrets and variables → Actions → **OPENAI_API_KEY**.
2) Clone locally and open as an Obsidian vault (install Obsidian Git to auto-pull).
