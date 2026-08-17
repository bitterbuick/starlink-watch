
import re
import sys
import time
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

# ---------- Resilient HTTP ----------
# CelesTrak and the news feeds occasionally time out or return a 5xx. A single
# unretried failure used to abort the whole scheduled run, so every fetch goes
# through here: bounded retries with exponential backoff, and an explicit
# FetchError so callers can decide whether to degrade instead of crash.
USER_AGENT = "starlink-watch/1.0 (+https://github.com/bitterbuick/starlink-watch)"
HTTP_TIMEOUT = (10, 60)   # (connect, read) seconds — never wait forever
HTTP_ATTEMPTS = 4

class FetchError(RuntimeError):
    """Raised when a URL could not be fetched after every retry."""

def _is_retryable(err):
    import requests
    if isinstance(err, (requests.exceptions.Timeout,
                        requests.exceptions.ConnectionError,
                        requests.exceptions.ChunkedEncodingError)):
        return True
    if isinstance(err, requests.exceptions.HTTPError):
        resp = getattr(err, "response", None)
        status = getattr(resp, "status_code", None)
        return status is not None and (status >= 500 or status == 429)
    return False

def http_get(url, timeout=HTTP_TIMEOUT, attempts=HTTP_ATTEMPTS, backoff=2.0, session=None):
    """GET `url`, retrying transient failures with exponential backoff.

    Retries connection/read timeouts and 429/5xx responses; a 4xx (other than
    429) fails immediately since retrying won't help. Raises FetchError when
    every attempt is exhausted.
    """
    import requests
    getter = session.get if session is not None else requests.get
    last = None
    for attempt in range(1, attempts + 1):
        try:
            resp = getter(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            return resp
        except Exception as err:
            last = err
            if attempt == attempts or not _is_retryable(err):
                break
            delay = backoff ** attempt   # 2s, 4s, 8s
            print(f"Fetch attempt {attempt}/{attempts} for {url} failed ({err}); "
                  f"retrying in {delay:.0f}s", file=sys.stderr)
            time.sleep(delay)
    raise FetchError(f"GET {url} failed after {attempts} attempt(s): {last}") from last

# ---------- Starlink-only filter with “criticism/event” signal ----------
POS = [
    r"\bstarlink\b",
    r"\bstarshield\b",
    r"\bspacex\b.*\bstarlink\b",
]
# Subjects that mean the story is about something *else*. These are checked
# against the headline only, and only when Starlink isn't in the headline:
# scanning the whole blob used to drop real Starlink stories for mentioning the
# ISS or a Falcon 9 in passing, which was the main source of missed items.
NEG = [
    r"\bstarship\b",
    r"\bfalcon\b\s?\d?\b",
    r"\bartemis\b|\biss\b|\bmars\b|\bcrew[- ]\d+\b|\bcargo\b",
    r"\boneweb\b|\bkuiper\b|\bblue origin\b|\bvirgin\b",
]
CRITICISM = [
    r"\b(outage|degrad\w*|down|jam\w*|spoof\w*|interference|rf interference|rfi|light pollution|streak\w*|reflection\w*|bright\w*)\b",
    r"\b(vulnerab\w*|exploit\w*|cve|hack\w*|breach\w*|compromise\w*|malware|apt|cisa|mitre|advisory|nation[- ]state|sanction\w*)\b",
    r"\b(debris|collision|re[- ]?entry|reentry|burn[- ]?up|deorbit\w*|emission\w*|soot|aluminum oxide|alumina|atmosphere|ozone|stratospher\w*)\b",
    r"\b(regulat\w*|proceeding\w*|filing\w*|fcc|itu|esa|noaa|faa|licen[cs]e\w*|policy|ban|restriction\w*|spectrum)\b",
    r"\b(astronomer\w*|observator\w*|telescope\w*|iau|darkit|dark sky|dark and quiet|survey\w*)\b",
    # Research, legal and civic signals — the same criticism, reported in a
    # register the original keyword set didn't cover.
    r"\b(study|studies|research\w*|scientist\w*|paper|preprint|findings?|peer[- ]review\w*)\b",
    r"\b(warn\w*|concern\w*|risk\w*|threat\w*|harm\w*|impact\w*|damage\w*|criticis\w*|critici[sz]\w*|backlash|protest\w*)\b",
    r"\b(lawsuit|sued?|court|litigation|complaint|petition|investigat\w*|probe|fine[ds]?|penalt\w*)\b",
    r"\b(pollut\w*|contaminat\w*|climate|environment\w*|emissions?)\b",
    r"\b(gps|navigation|radio astronomy|radio[- ]?quiet|conjunction|near miss|close approach|maneuver\w*|manoeuvr\w*)\b",
]
# Note: Added 'astronomer', 'observatory', etc to CRITICISM based on intent to capture astronomical impacts.


def _off_topic_headline(title: str) -> bool:
    """True when the headline is about another program and never names Starlink."""
    head = (title or "").lower()
    if re.search(r"\bstar\s?link\b|\bstarshield\b", head, re.I):
        return False
    return any(re.search(rx, head, re.I) for rx in NEG)


def looks_starlink_critical(title: str, summary: str, link: str) -> bool:
    t = " ".join([(title or ""), (summary or ""), (link or "")]).lower()
    if not any(re.search(rx, t, re.I) for rx in POS):
        return False
    if _off_topic_headline(title):
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
