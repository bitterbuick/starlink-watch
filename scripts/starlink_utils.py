
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

# ---------- Deterministic domain classification (no LLM needed) ----------
DOMAIN_KEYWORDS = {
    "Environmental": [
        r"\b(debris|collision|re[- ]?entry|reentry|burn[- ]?up|deorbit\w*|demis\w*)\b",
        r"\b(emission\w*|soot|black carbon|aluminum oxide|aluminium oxide|alumina|al2o3)\b",
        r"\b(atmospher\w*|stratospher\w*|mesospher\w*|ozone|climate|pollut\w*)\b",
        r"\b(noaa|esa|faa)\b.*\b(environment\w*|atmospher\w*|ozone)\b",
    ],
    "Cybersecurity": [
        r"\b(vulnerab\w*|exploit\w*|cve|hack\w*|breach\w*|compromise\w*|malware|apt)\b",
        r"\b(cisa|mitre|advisory|nation[- ]state|sanction\w*)\b",
        r"\b(jam\w*|spoof\w*|outage|degrad\w*|firmware|terminal\b.*\b(security|attack))\b",
    ],
    "Astronomical": [
        r"\b(astronom\w*|observator\w*|telescope\w*|iau|dark sky|dark and quiet)\b",
        r"\b(streak\w*|light pollution|bright\w*|reflection\w*|magnitude)\b",
        r"\b(rf interference|rfi|radio interference|radio[- ]quiet|radioastronom\w*)\b",
    ],
}

def classify_domain(title: str, summary: str, link: str = "") -> str:
    """Score an item against each domain's keyword set and return the best match.

    Ties break in the order Environmental > Cybersecurity > Astronomical
    (the order of DOMAIN_KEYWORDS). Items with no domain signal return "".
    """
    t = " ".join([(title or ""), (summary or ""), (link or "")]).lower()
    best_domain, best_score = "", 0
    for domain, patterns in DOMAIN_KEYWORDS.items():
        score = sum(len(re.findall(rx, t, re.I)) for rx in patterns)
        if score > best_score:
            best_domain, best_score = domain, score
    return best_domain
