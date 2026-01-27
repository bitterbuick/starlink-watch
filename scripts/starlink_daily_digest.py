#!/usr/bin/env python3
import os, sys, time, json, datetime, re, argparse
from pathlib import Path

try:
    import feedparser, yaml
except ImportError:
    print("Install deps: feedparser pyyaml", file=sys.stderr)
    sys.exit(1)

# Import shared utils
sys.path.append(str(Path(__file__).resolve().parent))
from starlink_utils import now_pt, looks_starlink_critical

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

FEEDS_FILE = REPO_ROOT / "scripts" / "feeds.yml"
if FEEDS_FILE.exists():
    FEEDS = yaml.safe_load(FEEDS_FILE.read_text())
else:
    FEEDS = {"feeds": []}

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

def gather_items():
    items = []
    now = datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(days=30)
    for f in FEEDS.get("feeds", []):
        try:
            d = feedparser.parse(f["url"])
        except Exception as e:
            print(f"Failed to parse {f.get('url')}: {e}", file=sys.stderr)
            continue

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

            title = getattr(e, "title", "") or ""
            summary = getattr(e, "summary", "") or ""
            link = getattr(e, "link", "") or ""

            if not looks_starlink_critical(title, summary, link):
                continue

            items.append({
                "source": f.get("name", f["url"]),
                "title": title,
                "summary": summary,
                "link": link,
                "date": dt.isoformat()
            })

    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:50]  # cap for cost

def openai_digest_json(items):
    import urllib.request
    if not OPENAI_API_KEY:
        print("OPENAI_API_KEY not set", file=sys.stderr)
        return None

    url = "https://api.openai.com/v1/chat/completions"
    today_str = now_pt().strftime("%Y-%m-%d")

    system = (
        "You are an AI assistant that generates a **Starlink-only** Daily Digest JSON. "
        "Filter for strict criticisms, risks, and concrete events in: "
        "Environmental, Cybersecurity, and Astronomical domains. "
        "Ignore marketing, generic launches, or non-Starlink items. "
        "Return a JSON object with this structure:\n"
        "{\n"
        "  \"digest_date\": \"YYYY-MM-DD\",\n"
        "  \"environmental_update\": boolean,\n"
        "  \"cybersecurity_update\": boolean,\n"
        "  \"astronomical_update\": boolean,\n"
        "  \"environmental_summary\": \"Text summary of env news...\",\n"
        "  \"cybersecurity_summary\": \"Text summary of cyber news...\",\n"
        "  \"astronomical_summary\": \"Text summary of astro news...\",\n"
        "  \"archive_environmental\": [ { \"date\": \"YYYY-MM-DD HH:mm PT\", \"headline\": \"...\", \"source\": \"...\", \"url\": \"...\" } ],\n"
        "  \"archive_cybersecurity\": [],\n"
        "  \"archive_astronomical\": []\n"
        "}\n"
        "If no new items, set update=false, summary to 'No Starlink-specific changes detected...', and archive list to empty."
    )
    
    user_content = f"Items JSON:\n{json.dumps(items, ensure_ascii=False)}\n\nGenerate digest for {today_str}."

    body = {
        "model": "gpt-4o-mini",
        "response_format": { "type": "json_object" },
        "messages": [{"role":"system","content":system},{"role":"user","content":user_content}],
        "temperature": 0.2
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type":"application/json","Authorization":f"Bearer {OPENAI_API_KEY}"}
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read().decode("utf-8"))
            content = out["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception as e:
        print(f"OpenAI API Error: {e}", file=sys.stderr)
        return None

def format_digest_markdown(data):
    today = data.get("digest_date", now_pt().strftime("%Y-%m-%d"))
    
    # Defaults
    env_sum = data.get("environmental_summary", "No updates.")
    cyb_sum = data.get("cybersecurity_summary", "No updates.")
    ast_sum = data.get("astronomical_summary", "No updates.")
    
    env_up = "Yes" if data.get("environmental_update") else "No"
    cyb_up = "Yes" if data.get("cybersecurity_update") else "No"
    ast_up = "Yes" if data.get("astronomical_update") else "No"

    md = f"""## Starlink Daily Digest — {today}

### Environmental
{env_sum}

### Cybersecurity
{cyb_sum}

### Astronomical
{ast_sum}

## Summary of Changes
| Domain | Updates Detected |
|-------|-------------------|
| Environmental | {env_up} |
| Cybersecurity | {cyb_up} |
| Astronomical  | {ast_up} |

"""
    
    # Archive sections (reconstruct format for append logic)
    # The append logic looks for "**Archive — Domain**" and lists.
    # We can just output them here.
    
    def format_archive(domain, items):
        out = f"**Archive — {domain}**\n"
        if not items:
            out += "No change\n"
        else:
            for i in items:
                # Format: - YYYY-MM-DD HH:mm PT | Headline | Source | URL
                out += f"- {i.get('date')} | {i.get('headline')} | {i.get('source')} | {i.get('url')}\n"
        return out

    md += format_archive("Environmental", data.get("archive_environmental", [])) + "\n"
    md += format_archive("Cybersecurity", data.get("archive_cybersecurity", [])) + "\n"
    md += format_archive("Astronomical", data.get("archive_astronomical", [])) + "\n"
    
    return md

RX_ARCHIVE = {
  "Environmental": r"(\*\*Archive\s+—\s+Environmental\*\*)([\s\S]*?)(\*\*Archive\s+—\s+Cybersecurity\*\*|\*\*Archive\s+—\s+Astronomical\*\*|$)",
  "Cybersecurity": r"(\*\*Archive\s+—\s+Cybersecurity\*\*)([\s\S]*?)(\*\*Archive\s+—\s+Astronomical\*\*|$)",
  "Astronomical":  r"(\*\*Archive\s+—\s+Astronomical\*\*)([\s\S]*?)$"
}

def append_archives(md):
    for domain, rx in RX_ARCHIVE.items():
        m = re.search(rx, md, re.I)
        if not m:
            continue
        body = (m.group(2) or "").strip()
        lines = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("- ")]
        if not lines:
            continue
        target = ARCHIVE / f"{domain}.md"
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        new_lines = [l for l in lines if l not in existing]
        if new_lines:
            existing = existing.rstrip() + "\n" + "\n".join(new_lines) + "\n"
            target.write_text(existing, encoding="utf-8")

def should_emit_now(force=False):
    if force or os.environ.get("FORCE_EMIT", "") == "1":
        return True
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Force run regardless of time")
    parser.add_argument("--dry-run", action="store_true", help="Don't query OpenAI, use mock data")
    args = parser.parse_args()

    if not should_emit_now(args.force):
        print("Not an emission window (PT) or already emitted this hour.")
        return

    items = gather_items()
    
    if args.dry_run:
        print(f"Dry run: Gathered {len(items)} items.")
        return

    json_data = openai_digest_json(items)
    if not json_data:
        print("Failed to generate digest JSON.")
        return
        
    md = format_digest_markdown(json_data)
    p = write_digest(md)
    append_archives(md)
    print(f"Wrote digest: {p}")

if __name__ == "__main__":
    main()

