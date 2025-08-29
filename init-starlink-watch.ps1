# init-starlink-watch.ps1
# Creates/updates the Starlink Watch repo layout.
# - Idempotent: only writes files if content changed; skips unchanged.
# - Adds .gitignore and .env.example
# - PT-aware Python script + GitHub Actions workflow + feeds

param(
  [string]$RootPath = (Get-Location).Path
)

$ErrorActionPreference = "Stop"

function New-Dir {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType Directory -Path $Path | Out-Null
  }
}

function Write-IfChanged {
  param(
    [string]$Path,
    [string]$Content
  )
  $dir = Split-Path -Parent $Path
  New-Dir -Path $dir
  $action = ""
  if (Test-Path -LiteralPath $Path) {
    $existing = Get-Content -LiteralPath $Path -Raw -ErrorAction SilentlyContinue
    if ($existing -ne $Content) {
      $Content | Out-File -FilePath $Path -Encoding UTF8 -Force
      $action = "modified"
    } else {
      $action = "skipped"
    }
  } else {
    $Content | Out-File -FilePath $Path -Encoding UTF8 -Force
    $action = "created"
  }
  return $action
}

# --- Paths ---
$root       = $RootPath
$vaultRoot  = Join-Path $root "Starlink Watch"
$archiveDir = Join-Path $vaultRoot "Archive"
$eventsDir  = Join-Path $vaultRoot "Events"
$scriptsDir = Join-Path $root "scripts"
$wfDir      = Join-Path $root ".github\workflows"
$stateDir   = Join-Path $root ".state"

# --- Ensure dirs ---
@($vaultRoot,$archiveDir,$eventsDir,$scriptsDir,$wfDir,$stateDir) | ForEach-Object { New-Dir $_ }

# --- File contents ---

$gitignore = @'
# Python
__pycache__/
*.pyc
*.pyo
*.pyd
*.egg-info/
.eggs/
.venv/
venv/
ENV/

# Local state
.state/

# OS
.DS_Store
Thumbs.db

# Secrets (local only)
.env
'@

$envExample = @'
# Local testing only. Do NOT commit your real .env.
OPENAI_API_KEY=sk-your-key-here
# Optional if you test locally writing into another vault
OBSIDIAN_VAULT=C:/path/to/your/obsidian/vault
'@

$feedsYml = @'
feeds:
  - name: SpaceNews
    url: https://spacenews.com/feed/
  - name: Space.com (All)
    url: https://www.space.com/feeds/all
  - name: Scientific American – Space
    url: https://www.scientificamerican.com/feed/space/
  - name: Guardian – Environment
    url: https://www.theguardian.com/environment/rss
  - name: CISA Current Activity
    url: https://www.cisa.gov/news-events/cisa-updates.xml
  - name: SecurityWeek
    url: https://www.securityweek.com/feed/
  - name: ESA – Space Safety
    url: https://www.esa.int/rssfeed/Our_Activities/Space_Safety
'@

$scriptPy = @'
#!/usr/bin/env python3
import os, sys, time, json, datetime, re
from pathlib import Path

try:
    import feedparser, yaml
except ImportError:
    print("Install deps: feedparser pyyaml", file=sys.stderr)
    sys.exit(1)

# ---- Pacific Time (PT) ----
try:
    from zoneinfo import ZoneInfo
    PT = ZoneInfo("America/Los_Angeles")
except Exception:
    PT = None

def now_pt():
    if PT:
        return datetime.datetime.now(tz=PT)
    return datetime.datetime.utcnow() - datetime.timedelta(hours=7)

REPO_ROOT = Path(__file__).resolve().parents[1]
VAULT = REPO_ROOT
ROOT = VAULT / "Starlink Watch"
EVENTS = ROOT / "Events"
ARCHIVE = ROOT / "Archive"
STATE = REPO_ROOT / ".state"

for p in (EVENTS, ARCHIVE, STATE):
    p.mkdir(parents=True, exist_ok=True)

# Ensure archive files exist
for name in ("Environmental.md", "Cybersecurity.md", "Astronomical.md"):
    f = ARCHIVE / name
    if not f.exists():
        f.write_text(f"# {name.split('.')[0]} — Archive\n", encoding="utf-8")

FEEDS = yaml.safe_load((REPO_ROOT / "scripts" / "feeds.yml").read_text())
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
if not OPENAI_API_KEY:
    print("OPENAI_API_KEY not set", file=sys.stderr)
    sys.exit(2)

def gather_items():
    items = []
    now = datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(days=30)
    for f in FEEDS.get("feeds", []):
        d = feedparser.parse(f["url"])
        for e in d.entries:
            dt = None
            for key in ("published_parsed","updated_parsed"):
                val = getattr(e, key, None)
                if val:
                    dt = datetime.datetime.fromtimestamp(time.mktime(val))
                    break
            if not dt:
                dt = now
            if dt < cutoff:
                continue
            items.append({
                "source": f.get("name", f["url"]),
                "title": getattr(e, "title", ""),
                "summary": getattr(e, "summary", ""),
                "link": getattr(e, "link", ""),
                "date": dt.isoformat()
            })
    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:60]

def openai_digest(items):
    import urllib.request, json as js
    url = "https://api.openai.com/v1/chat/completions"
    today_str = now_pt().strftime("%Y-%m-%d")
    system = (
        "You generate a consolidated Starlink Daily Digest from feed items. "
        "Structure: Environmental, Cybersecurity, Astronomical; then Summary of Changes; "
        "then three sections named exactly: **Archive — Environmental**, **Archive — Cybersecurity**, **Archive — Astronomical**. "
        "Each archive section must contain bullets in this exact format:\\n"
        "- YYYY-MM-DD HH:mm PT | Headline | Source | URL\\n"
        "Keep it concise, factual, and link to sources that appear in the items list only."
    )
    user = f"Items JSON:\\n{json.dumps(items, ensure_ascii=False)}\\n\\nWrite: Starlink Daily Digest — {today_str}"
    body = {
        "model": "gpt-4o-mini",
        "messages": [{"role":"system","content":system},{"role":"user","content":user}],
        "temperature": 0.3
    }
    req = urllib.request.Request(
        url,
        data=js.dumps(body).encode("utf-8"),
        headers={"Content-Type":"application/json","Authorization":f"Bearer {OPENAI_API_KEY}"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        out = js.loads(r.read().decode("utf-8"))
    return out["choices"][0]["message"]["content"]

RX = {
  "Environmental": r"(\*\*Archive\s+—\s+Environmental\*\*)([\s\S]*?)(\*\*Archive\s+—\s+Cybersecurity\*\*|\*\*Archive\s+—\s+Astronomical\*\*|$)",
  "Cybersecurity": r"(\*\*Archive\s+—\s+Cybersecurity\*\*)([\s\S]*?)(\*\*Archive\s+—\s+Astronomical\*\*|$)",
  "Astronomical":  r"(\*\*Archive\s+—\s+Astronomical\*\*)([\s\S]*?)$"
}

def append_archives(md):
    for domain, rx in RX.items():
        m = re.search(rx, md, re.I)
        if not m:
            continue
        body = (m.group(2) or "").trim() if hasattr(str, "trim") else (m.group(2) or "").strip()
        lines = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("- ")]
        if not lines:
            continue
        target = ARCHIVE / f"{domain}.md"
        existing = target.read_text(encoding="utf-8")
        new_lines = [l for l in lines if l not in existing]
        if new_lines:
            existing = existing.rstrip() + "\n" + "\n".join(new_lines) + "\n"
            target.write_text(existing, encoding="utf-8")

def should_emit_now():
    t = now_pt()
    hour = t.hour
    mark = STATE / f"run_{t.strftime('%Y%m%d_%H')}.flag"
    desired = hour in (9, 17)  # PT windows
    if not desired:
        return False
    if mark.exists():
        return False
    mark.write_text("ok", encoding="utf-8")
    return True

def write_digest(md):
    t = now_pt()
    fname = f"{t.strftime('%Y-%m-%d_%H%M')} — Starlink Daily Digest.md"
    path = EVENTS / fname
    path.write_text(md, encoding="utf-8")
    return path

def main():
    if not should_emit_now():
        print("Not an emission window (PT) or already emitted this hour.")
        return
    items = gather_items()
    if not items:
        print("No feed items found.")
        return
    md = openai_digest(items)
    p = write_digest(md)
    append_archives(md)
    print(f"Wrote digest: {p}")

if __name__ == "__main__":
    main()
'@

$workflow = @'
name: Starlink Daily Digest

on:
  schedule:
    - cron: "0 * * * *"   # run hourly in UTC; script self-gates to 09:00/17:00 PT
  workflow_dispatch: {}

jobs:
  run:
    runs-on: ubuntu-latest
    env:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install feedparser pyyaml

      - name: Generate digest (PT-aware)
        run: |
          python scripts/starlink_daily_digest.py

      - name: Commit & push if changed
        run: |
          git config user.name  "starlink-bot"
          git config user.email "starlink-bot@users.noreply.github.com"
          git add -A
          git diff --cached --quiet || (git commit -m "Update Starlink Daily Digest" && git push)
'@

$readme = @'
# Starlink Watch (Cloud Automation)

- Runs hourly in GitHub Actions; emits only at **09:00** and **17:00 PT**.
- Writes `Starlink Watch/Events/<timestamp> — Starlink Daily Digest.md`
- Appends bullets to `Starlink Watch/Archive/*.md`

## Setup
1) Repo → Settings → Secrets and variables → Actions → **OPENAI_API_KEY**.
2) Clone locally and open as an Obsidian vault (install Obsidian Git to auto-pull).
'@

# --- Archive seed files ---
$log = @()
$log += "Astronomical.md : " + (Write-IfChanged -Path (Join-Path $archiveDir "Astronomical.md")   -Content "# Astronomical — Archive`r`n")
$log += "Cybersecurity.md: " + (Write-IfChanged -Path (Join-Path $archiveDir "Cybersecurity.md") -Content "# Cybersecurity — Archive`r`n")
$log += "Environmental.md: " + (Write-IfChanged -Path (Join-Path $archiveDir "Environmental.md") -Content "# Environmental — Archive`r`n")

# --- Script, feeds, workflow, gitignore, env.example, readme ---
$log += "scripts\\feeds.yml        : " + (Write-IfChanged -Path (Join-Path $scriptsDir "feeds.yml") -Content $feedsYml)
$log += "scripts\\starlink_*.py    : " + (Write-IfChanged -Path (Join-Path $scriptsDir "starlink_daily_digest.py") -Content $scriptPy)
$log += ".github\\workflows\\*.yml : " + (Write-IfChanged -Path (Join-Path $wfDir "starlink.yml") -Content $workflow)
$log += ".gitignore               : " + (Write-IfChanged -Path (Join-Path $root ".gitignore") -Content $gitignore)
$log += ".env.example             : " + (Write-IfChanged -Path (Join-Path $root ".env.example") -Content $envExample)
$log += "README.md                : " + (Write-IfChanged -Path (Join-Path $root "README.md") -Content $readme)

# --- Summary ---
Write-Host "`nChanges:" -ForegroundColor Cyan
$log | ForEach-Object { Write-Host "  $_" }
Write-Host "`nDone. Next:" -ForegroundColor Green
Write-Host "  1) git add -A"
Write-Host "  2) git commit -m 'Bootstrap or update Starlink Watch'"
Write-Host "  3) git push"
Write-Host "  4) In GitHub → Settings → Secrets → Actions → add OPENAI_API_KEY"
Write-Host "  5) Actions will run hourly; digests at 09:00 & 17:00 PT"
