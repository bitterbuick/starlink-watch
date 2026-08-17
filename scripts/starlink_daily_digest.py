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
from starlink_utils import now_pt, looks_starlink_critical, classify_domain, http_get

REPO_ROOT = Path(__file__).resolve().parents[1]
VAULT = REPO_ROOT
ROOT = VAULT / "Starlink Watch"
EVENTS = ROOT / "Events"
ARCHIVE = ROOT / "Archive"
STATE = REPO_ROOT / ".state"

for p in (EVENTS, ARCHIVE, STATE):
    p.mkdir(parents=True, exist_ok=True)

# Domains, in report order. "Regulatory" is the catch-all: an item that clears
# the Starlink-criticism filter but matches none of the three topic vocabularies
# used to be discarded silently, which is how legal, policy and FCC stories went
# missing from the digest.
DOMAINS = ("Environmental", "Cybersecurity", "Astronomical", "Regulatory")
FALLBACK_DOMAIN = "Regulatory"

# Ensure archive files exist
for name in DOMAINS:
    f = ARCHIVE / f"{name}.md"
    if not f.exists():
        f.write_text(f"# {name} — Archive\n", encoding="utf-8")

FEEDS_FILE = REPO_ROOT / "scripts" / "feeds.yml"
if FEEDS_FILE.exists():
    FEEDS = yaml.safe_load(FEEDS_FILE.read_text())
else:
    FEEDS = {"feeds": []}

MAX_ITEMS = 80
FEED_HEALTH_FILE = REPO_ROOT / "data" / "feed_health.json"

# No single feed is worth much waiting, and there are a lot of them: keep the
# per-feed retries short and cap the whole pass so a run of slow feeds can't
# push the job into its timeout. Anything not reached is reported as skipped.
FEED_TIMEOUT = (5, 20)
FEED_ATTEMPTS = 2
FEED_BUDGET_SECONDS = 420

# Google News and the like append " - Publisher" to headlines; strip it so the
# same story arriving from two feeds collapses into one item.
RX_TITLE_SUFFIX = re.compile(r"\s+[-–—|]\s+[^-–—|]{2,40}$")


def title_key(title):
    """Normalized headline used to dedupe the same story across feeds."""
    text = RX_TITLE_SUFFIX.sub("", (title or "").strip())
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def dedupe_items(items):
    """Keep the first occurrence of each story; feeds overlap heavily."""
    out, seen_titles, seen_links = [], set(), set()
    for item in items:
        tkey = title_key(item["title"])
        link = (item.get("link") or "").strip()
        if (tkey and tkey in seen_titles) or (link and link in seen_links):
            continue
        if tkey:
            seen_titles.add(tkey)
        if link:
            seen_links.add(link)
        out.append(item)
    return out


def gather_items():
    items = []
    health = []
    now = datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(days=30)
    started = time.monotonic()
    for f in FEEDS.get("feeds", []):
        name = f.get("name", f["url"])
        if time.monotonic() - started > FEED_BUDGET_SECONDS:
            print(f"Feed budget exhausted; skipping {name}", file=sys.stderr)
            health.append({"name": name, "status": "skipped", "entries": 0,
                           "recent": 0, "matched": 0,
                           "detail": "not reached within the feed time budget"})
            continue
        # Fetch ourselves rather than letting feedparser open the URL: it has no
        # timeout, so one unresponsive feed could hang the scheduled run.
        try:
            d = feedparser.parse(
                http_get(f["url"], timeout=FEED_TIMEOUT, attempts=FEED_ATTEMPTS).content)
        except Exception as err:
            print(f"Failed to fetch {f.get('url')}: {err}", file=sys.stderr)
            health.append({"name": name, "status": "error", "entries": 0,
                           "recent": 0, "matched": 0, "detail": str(err)[:200]})
            continue

        entries = recent = matched = 0
        for entry in d.entries:
            entries += 1
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
            recent += 1

            title = getattr(entry, "title", "") or ""
            summary = getattr(entry, "summary", "") or ""
            link = getattr(entry, "link", "") or ""

            if not looks_starlink_critical(title, summary, link):
                continue
            matched += 1

            items.append({
                "source": name,
                "title": title,
                "summary": summary,
                "link": link,
                "date": dt.isoformat()
            })

        status = "ok" if entries else "empty"
        health.append({"name": name, "status": status, "entries": entries,
                       "recent": recent, "matched": matched, "detail": ""})
        print(f"{name}: {entries} entries, {recent} within 30d, {matched} matched")

    items.sort(key=lambda x: x["date"], reverse=True)
    items = dedupe_items(items)[:MAX_ITEMS]
    write_feed_health(health, len(items))
    return items


def write_feed_health(health, kept):
    """Publish per-feed yield so a quiet digest is diagnosable, not mysterious."""
    ok = [h for h in health if h["status"] == "ok"]
    payload = {
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feeds_configured": len(health),
        "feeds_ok": len(ok),
        "feeds_failed": len([h for h in health if h["status"] == "error"]),
        "feeds_empty": len([h for h in health if h["status"] == "empty"]),
        "feeds_skipped": len([h for h in health if h["status"] == "skipped"]),
        "entries_seen": sum(h["entries"] for h in health),
        "entries_recent": sum(h["recent"] for h in health),
        "items_matched": sum(h["matched"] for h in health),
        "items_kept": kept,
        "feeds": sorted(health, key=lambda h: (-h["matched"], h["name"])),
    }
    FEED_HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    FEED_HEALTH_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Feeds: {payload['feeds_ok']}/{payload['feeds_configured']} ok, "
          f"{payload['entries_recent']} recent entries, "
          f"{payload['items_matched']} matched, {kept} kept after dedupe.")

# ---------- Deterministic digest (no external API) ----------
SEEN_FILE = STATE / "seen_items.json"

SEEN_CAP = 2000

def load_seen():
    """Keys of already-digested items, oldest first."""
    if SEEN_FILE.exists():
        try:
            return list(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
        except Exception:
            return []
    return []

def save_seen(seen):
    # Cap the file so it can't grow without bound, keeping the most recent keys.
    # (Sorting before truncating used to drop keys alphabetically, which could
    # evict a recent link and let an old story resurface.)
    SEEN_FILE.write_text(json.dumps(list(seen)[-SEEN_CAP:]), encoding="utf-8")

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
    seen_lookup = set(seen)

    buckets = {name: [] for name in DOMAINS}
    for item in items:
        if item_key(item) in seen_lookup:
            continue
        domain = classify_domain(item["title"], item["summary"], item["link"])
        buckets[domain if domain in buckets else FALLBACK_DOMAIN].append(item)

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

    data = {"digest_date": today_str}
    for name in DOMAINS:
        slug = name.lower()
        data[f"{slug}_update"] = bool(buckets[name])
        data[f"{slug}_summary"] = summarize_domain(name, buckets[name])
        data[f"archive_{slug}"] = archive_entries(buckets[name])

    for domain_items in buckets.values():
        for i in domain_items:
            key = item_key(i)
            if key not in seen_lookup:
                seen_lookup.add(key)
                seen.append(key)
    save_seen(seen)

    return data

def format_digest_markdown(data):
    today = data.get("digest_date", now_pt().strftime("%Y-%m-%d"))

    sections = "\n".join(
        f"### {name}\n{data.get(f'{name.lower()}_summary', 'No updates.')}\n"
        for name in DOMAINS
    )
    table_rows = "\n".join(
        f"| {name} | {'Yes' if data.get(f'{name.lower()}_update') else 'No'} |"
        for name in DOMAINS
    )

    md = f"""## Starlink Daily Digest — {today}

{sections}
## Summary of Changes
| Domain | Updates Detected |
|-------|-------------------|
{table_rows}

"""

    # Archive sections (reconstruct format for append logic)
    # The append logic looks for "**Archive — Domain**" and lists.

    def format_archive(domain, items):
        out = f"**Archive — {domain}**\n"
        if not items:
            out += "No change\n"
        else:
            for i in items:
                # Bold headline so build_site.py's archive parser picks the entry up
                out += f"- {i.get('date')} | **{i.get('headline')}** — {i.get('source')} {i.get('url')}\n"
        return out

    for name in DOMAINS:
        md += format_archive(name, data.get(f"archive_{name.lower()}", [])) + "\n"

    return md


def _archive_rx(domain):
    """Match one archive block, stopping at whichever archive header comes next."""
    later = "|".join(rf"\*\*Archive\s+—\s+{d}\*\*" for d in DOMAINS if d != domain)
    return rf"(\*\*Archive\s+—\s+{domain}\*\*)([\s\S]*?)({later}|$)"

RX_ARCHIVE = {name: _archive_rx(name) for name in DOMAINS}

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

def run_flag(force=False):
    """Path of the once-per-window marker: UTC hour when forced, PT hour otherwise."""
    t = datetime.datetime.utcnow() if (force or os.environ.get("FORCE_EMIT", "") == "1") else now_pt()
    return STATE / f"run_{t.strftime('%Y%m%d_%H')}.flag"

def mark_emitted(force=False):
    """Claim this window — only once the digest has actually been written, so a
    run that dies mid-flight doesn't lock out its own retry."""
    run_flag(force).write_text("ok", encoding="utf-8")

def should_emit_now(force=False):
    if force or os.environ.get("FORCE_EMIT", "") == "1":
        # Still prevent double-emission in the same UTC hour (e.g. workflow reruns)
        if run_flag(force).exists():
            print("Already emitted this UTC hour; skipping duplicate.")
            return False
        return True
    # Fallback: only emit at the scheduled PT hours when run manually without --force
    if now_pt().hour not in (9, 17):
        return False
    return not run_flag(force).exists()

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
    mark_emitted(args.force)
    print(f"Wrote digest: {p}")

if __name__ == "__main__":
    main()

