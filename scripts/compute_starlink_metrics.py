#!/usr/bin/env python3
import csv, json, math, re, time, datetime, pathlib, io
from pathlib import Path
import requests
import yaml
from bs4 import BeautifulSoup  # lightweight HTML parsing for decayed list

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
STATE = REPO / ".state"
SITE  = REPO / "site"
DATA.mkdir(exist_ok=True, parents=True)
STATE.mkdir(exist_ok=True, parents=True)
(SITE / "assets").mkdir(exist_ok=True, parents=True)

CFG = yaml.safe_load((DATA / "starlink_config.yml").read_text(encoding="utf-8"))

STARLINK_CSV = CFG["endpoints"]["starlink_gp_csv"]
DECAYED_HTML = CFG["endpoints"]["decayed_recent_html"]

def ts():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def fetch_starlink_active_count():
    resp = requests.get(STARLINK_CSV, timeout=60)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    rows = [row for row in reader]
    # Filter only rows whose OBJECT_NAME contains 'STARLINK'
    rows = [row for row in rows if "STARLINK" in (row.get("OBJECT_NAME","").upper())]
    return len(rows)

def fetch_recent_decayed_starlink():
    """Parse CelesTrak 'recently decayed' page; accumulate STARLINK- entries into a set for historical total."""
    resp = requests.get(DECAYED_HTML, timeout=60)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    # Match chunks like "... 47995, STARLINK-2309 ; ..."
    ids = set(re.findall(r"\bSTARLINK-\d+\b", text.upper()))
    # Merge into persistent set
    store = STATE / "decayed_starlinks.json"
    seen = set()
    if store.exists():
        seen = set(json.loads(store.read_text(encoding="utf-8")))
    seen |= ids
    store.write_text(json.dumps(sorted(seen)), encoding="utf-8")
    return len(seen)

def weighted_mass(count, mix):
    m = CFG["masses"]
    # normalize weights
    total_w = sum(max(0.0, mix.get(k, 0.0)) for k in ("v1","v15","v2m")) or 1.0
    w = {k: max(0.0, mix.get(k, 0.0))/total_w for k in ("v1","v15","v2m")}
    avg = w["v1"]*m["v1"] + w["v15"]*m["v15"] + w["v2m"]*m["v2m"]
    return count * avg

def alumina_from_reentry(kg_reentered):
    f_al = float(CFG.get("aluminum_fraction_of_satellite", 0.7))
    yield_coeff = float(CFG.get("alumina_kg_per_kg_aluminum", 1.89))
    return kg_reentered * f_al * yield_coeff

def rolling_series_push(series_file, point):
    ser = []
    if series_file.exists():
        ser = json.loads(series_file.read_text(encoding="utf-8"))
    ser.append(point)
    # retention
    days = int(CFG.get("retention_days", 120))
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    ser = [p for p in ser if p["date"] >= cutoff]
    series_file.write_text(json.dumps(ser, indent=2), encoding="utf-8")
    return ser

def main():
    active = fetch_starlink_active_count()
    decayed_total = fetch_recent_decayed_starlink()  # keeps a running total

    # Mass estimates
    on_orbit_mass = weighted_mass(active, CFG["mix_active"])              # kg
    reentered_mass = weighted_mass(decayed_total, CFG["mix_decayed"])     # kg (historical)
    alumina_kg = alumina_from_reentry(reentered_mass)

    # Persist single snapshot
    metrics = {
        "generated_at": ts(),
        "active_count": active,
        "decayed_total": decayed_total,
        "on_orbit_mass_kg": round(on_orbit_mass, 1),
        "reentered_mass_kg": round(reentered_mass, 1),
        "alumina_kg": round(alumina_kg, 1),
        "assumptions": {
            "masses": CFG["masses"],
            "mix_active": CFG["mix_active"],
            "mix_decayed": CFG["mix_decayed"],
            "aluminum_fraction": CFG["aluminum_fraction_of_satellite"],
            "alumina_yield": CFG["alumina_kg_per_kg_aluminum"]
        },
        "sources": {
            "celestrak_gp_csv": STARLINK_CSV,
            "celestrak_decayed": DECAYED_HTML
        }
    }
    (DATA / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    # Persist time series (for charts)
    date = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    series_dir = DATA / "series"
    series_dir.mkdir(exist_ok=True)
    rolling_series_push(series_dir / "active_count.json", {"date": date, "value": active})
    rolling_series_push(series_dir / "on_orbit_mass_kg.json", {"date": date, "value": round(on_orbit_mass,1)})
    rolling_series_push(series_dir / "reentered_mass_kg.json", {"date": date, "value": round(reentered_mass,1)})
    rolling_series_push(series_dir / "alumina_kg.json", {"date": date, "value": round(alumina_kg,1)})

    print(f"Metrics computed: {active} active, {decayed_total} decayed, {round(on_orbit_mass,1)} kg on-orbit, {round(alumina_kg,1)} kg alumina")

if __name__ == "__main__":
    main()
