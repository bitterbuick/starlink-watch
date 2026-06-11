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
from starlink_utils import now_pt, looks_starlink_critical, classify_domain

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

def gather_items():
    items = []
    now = datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(days=30)
    for f in FEEDS.get("feeds", []):
        try:
            d = feedparser.parse(f["url"])
        except Exception as err:
            print(f"Failed to parse {f.get('url')}: {err}", file=sys.stderr)
            continue

        for entry in d.entries:
            dt = None
            for key in ("published_parsed","updated_parsed"):
                val = getattr(entry, key, None)
                if val:
                    dt = datetime.datetime.fromtimestamp(time.mktime(val))
                    break
            if not dt:
                dt = now
            if dt < cutoff:
                continue

            title = getattr(entry, "title", "") or ""
            summary = getattr(entry, "summary", "") or ""
            link = getattr(entry, "link", "") or ""

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
    return items[:50]

# ---------- Deterministic digest (no external API) ----------
SEEN_FILE = STATE / "seen_items.json"

def load_seen():
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()

def save_seen(seen):
    # Cap the file so it can't grow without bound; old links age out of feeds anyway
    SEEN_FILE.write_text(json.dumps(sorted(seen)[-2000:]), encoding="utf-8")

def item_key(item):
    return item.get("link") or item.get("title", "")

def summarize_domain(domain, new_items):
    if not new_items:
        return f"No new Starlink-specific {domain.lower()} items detected in monitored feeds."
    heads = "; ".join(
        f"“{i['title']}” ({i['source']})" for i in new_items[:3]
    )
    more = f" Plus {len(new_items) - 3} more item(s) in the archive below." if len(new_items) > 3 else ""
    return f"{len(new_items)} new item(s) flagged: {heads}.{more}"

def build_digest_data(items):
    """Bucket filtered feed items into domains and build the digest structure
    that format_digest_markdown expects — pure keyword logic, no LLM."""
    today_str = now_pt().strftime("%Y-%m-%d")
    seen = load_seen()

    buckets = {"Environmental": [], "Cybersecurity": [], "Astronomical": []}
    for item in items:
        if item_key(item) in seen:
            continue
        domain = classify_domain(item["title"], item["summary"], item["link"])
        if domain in buckets:
            buckets[domain].append(item)

    def archive_entries(domain_items):
        out = []
        for i in domain_items:
            date = (i.get("date") or today_str)[:10]
            out.append({
                "date": date,
                "headline": i["title"].strip(),
                "source": i["source"].strip(),
                "url": i["link"].strip(),
            })
        return out

    data = {
        "digest_date": today_str,
        "environmental_update": bool(buckets["Environmental"]),
        "cybersecurity_update": bool(buckets["Cybersecurity"]),
        "astronomical_update": bool(buckets["Astronomical"]),
        "environmental_summary": summarize_domain("Environmental", buckets["Environmental"]),
        "cybersecurity_summary": summarize_domain("Cybersecurity", buckets["Cybersecurity"]),
        "astronomical_summary": summarize_domain("Astronomical", buckets["Astronomical"]),
        "archive_environmental": archive_entries(buckets["Environmental"]),
        "archive_cybersecurity": archive_entries(buckets["Cybersecurity"]),
        "archive_astronomical": archive_entries(buckets["Astronomical"]),
    }

    for domain_items in buckets.values():
        seen.update(item_key(i) for i in domain_items)
    save_seen(seen)

    return data

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
                # Bold headline so build_site.py's archive parser picks the entry up
                out += f"- {i.get('date')} | **{i.get('headline')}** — {i.get('source')} {i.get('url')}\n"
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
        # Still prevent double-emission in the same UTC hour (e.g. workflow reruns)
        t = datetime.datetime.utcnow()
        mark = STATE / f"run_{t.strftime('%Y%m%d_%H')}.flag"
        if mark.exists():
            print("Already emitted this UTC hour; skipping duplicate.")
            return False
        mark.write_text("ok", encoding="utf-8")
        return True
    # Fallback: only emit at the scheduled PT hours when run manually without --force
    t = now_pt()
    hour = t.hour
    mark = STATE / f"run_{t.strftime('%Y%m%d_%H')}.flag"
    if hour not in (9, 17):
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
    parser.add_argument("--dry-run", action="store_true", help="Gather and classify items without writing the digest")
    args = parser.parse_args()

    if not should_emit_now(args.force):
        print("Not an emission window (PT) or already emitted this hour.")
        return

    items = gather_items()

    if args.dry_run:
        print(f"Dry run: Gathered {len(items)} items.")
        for i in items:
            print(f"  [{classify_domain(i['title'], i['summary'], i['link']) or '??'}] {i['title']}")
        return

    json_data = build_digest_data(items)
    md = format_digest_markdown(json_data)
    p = write_digest(md)
    append_archives(md)
    print(f"Wrote digest: {p}")

if __name__ == "__main__":
    main()

