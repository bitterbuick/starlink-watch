
import re
import datetime

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
    r"\b(outage|degrad\w*|down|jam\w*|spoof\w*|interference|rf interference|rfi|light pollution|streak\w*|reflection\w*|bright\w*)\b",
    r"\b(vulnerab\w*|exploit\w*|cve|hack\w*|breach\w*|compromise\w*|malware|apt|cisa|mitre|advisory|nation[- ]state|sanction\w*)\b",
    r"\b(debris|collision|re[- ]?entry|reentry|burn[- ]?up|deorbit\w*|emission\w*|soot|aluminum oxide|alumina|atmosphere|ozone)\b",
    r"\b(regulat\w*|proceeding\w*|filing\w*|fcc|itu|esa|noaa|faa|licen[cs]e\w*|policy|ban|restriction\w*)\b",
    r"\b(astronomer\w*|observatory|telescope\w*|iau|darkit|dark sky)\b",
]
# Note: Added 'astronomer', 'observatory', etc to CRITICISM based on intent to capture astronomical impacts.

def looks_starlink_critical(title: str, summary: str, link: str) -> bool:
    t = " ".join([(title or ""), (summary or ""), (link or "")]).lower()
    if not any(re.search(rx, t, re.I) for rx in POS):
        return False
    if any(re.search(rx, t, re.I) for rx in NEG):
        return False
    # require criticism/event signal (not marketing or generic launch)
    return any(re.search(rx, t, re.I) for rx in CRITICISM)
