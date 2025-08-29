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

# ---------- Starlink-only filter with “criticism/event” signal ----------
POS = [
    r"\bstarlink\b",
    r"\bstarshield\b",
    r"\bspacex\b.*\bstarlink\b",
]
NEG = [
    r"\bstarship\b(?!.*\bstarlink\b)",
    r"\bfalcon\b\s?\d?\b(?!.*\bstarlink\b)",
    r"\bartemis\b|\biss\b|\bmars\b|\bcrew[- ]\d+\b|\bcargo\b",
    r"\boneweb\b|\bkuiper\b|\bblue origin\b|\bvirgin\b",
]
CRITICISM = [
    r"\b(outage|degrad|down|jam|jamming|spoof|interference|rf interference|rfi|light pollution|streak|reflection|bright(ness)?)\b",
    r"\b(vulnerab|exploit|cve|hack|breach|compromise|malware|apt|cisa|mitre|advisory|nation[- ]state|sanction)\b",
    r"\b(debris|collision|re[- ]?entry|reentry|burn[- ]?up|deorbit|emission|soot|aluminum oxide|alumina|atmosphere|ozone)\b",
    r"\b(regulat(ion|ory)|proceeding|filing|fcc|itu|esa|noaa|faa|licen[cs]e|policy|ban|restriction)\b",
]
def looks_starlink_critical(title: str, summary: str, link: str) -> bool:
    t = " ".join([(title or ""), (summary or ""), (link or "")]).lower()
    if not any(re.search(rx, t, re.I) for rx in POS):
        return False
    if any(re.search(rx, t, re.I) for rx in NEG):
        return False
    # require criticism/event signal (not marketing or generic launch)
    return any(re.search(rx, t, re.I) for rx in CRITICISM)
# -----------------------------------------------------------------------

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
    return items[:40]  # cap for cost
# -----------------------------------------------------------------------

def openai_digest(items):
    import urllib.request, json as js
    url = "https://api.openai.com/v1/chat/completions"
    today_str = now_pt().strftime("%Y-%m-%d")

    if not items:
        return f"""## Starlink Daily Digest — {today_str}

### Environmental
- No **Starlink-specific** environmental developments (re-entries, emissions, debris, regulatory actions) since last check.

### Cybersecurity
- No **Starlink-specific** cybersecurity developments (terminal/dish vulns, incidents, nation-state targeting, advisories) since last check.

### Astronomical
- No **Starlink-specific** astronomical impacts (optical streaks, RFI results, mitigation updates, survey contamination, visible trains) since last check.

## Summary of Changes
| Domain | Updates Detected |
|-------|-------------------|
| Environmental | No |
| Cybersecurity | No |
| Astronomical  | No |

**Archive — Environmental**
No change

**Archive — Cybersecurity**
No change

**Archive — Astronomical**
No change
"""

    system = (
        "You generate a **Starlink-only** Daily Digest, focusing strictly on criticisms, risks, and concrete events:"
        " Environmental (re-entries, emissions/soot, debris, regulatory actions),"
        " Cybersecurity (vulnerabilities/exploits/incidents/targeting/advisories/policy actions),"
        " Astronomical (optical streaks, RFI, mitigation updates, survey contamination, visible trains). "
        "Ignore marketing, generic launches, or non-Starlink items. "
        "Structure: three domain sections; then a 'Summary of Changes' table; "
        "then three sections named exactly: **Archive — Environmental**, **Archive — Cybersecurity**, **Archive — Astronomical**. "
        "In each Archive section, list new items as bullets in this exact format:\n"
        "- YYYY-MM-DD HH:mm PT | Headline | Source | URL\n"
        "Be concise, factual, link to provided items only."
    )
    user = f"Items JSON (already filtered to Starlink criticisms/events):\n{json.dumps(items, ensure_ascii=False)}\n\nWrite: Starlink Daily Digest — {today_str}"
    body = {
        "model": "gpt-4o-mini",
        "messages": [{"role":"system","content":system},{"role":"user","content":user}],
        "temperature": 0.2
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type":"application/json","Authorization":f"Bearer {OPENAI_API_KEY}"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read().decode("utf-8"))
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
        body = (m.group(2) or "").strip()
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
    if os.environ.get("FORCE_EMIT", "") == "1":
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
    if not should_emit_now():
        print("Not an emission window (PT) or already emitted this hour.")
        return
    items = gather_items()
    md = openai_digest(items)
    p = write_digest(md)
    append_archives(md)
    print(f"Wrote digest: {p}")

if __name__ == "__main__":
    main()
