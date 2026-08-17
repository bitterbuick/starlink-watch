#!/usr/bin/env python3
"""Starlink in context: the whole catalogue, split Starlink vs everything else.

The rest of the pipeline measures Starlink alone, which answers "how much?" but
not "compared to what?". This script reads CelesTrak's full SATCAT — every
tracked object ever launched, with decay dates — and produces the two deltas:

  * on-orbit mass, Starlink vs all other catalogued objects;
  * re-entered mass and the Al₂O₃ it implies, per year, with and without
    Starlink.

SATCAT publishes radar cross-section, not mass, so non-Starlink masses are
estimated from RCS with a per-type clamp (see `space_totals` in
data/starlink_config.yml). Starlink objects reuse the generation mass mix the
rest of the site already uses, so the numbers stay consistent. Everything is an
estimate and is labelled as one on the site.
"""
import csv, datetime, io, json, sys
from pathlib import Path

import yaml

sys.path.append(str(Path(__file__).resolve().parent))
from starlink_utils import http_get, FetchError

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"

CFG = yaml.safe_load((DATA / "starlink_config.yml").read_text(encoding="utf-8"))
TOTALS_CFG = CFG.get("space_totals", {})
SATCAT_CSV = CFG["endpoints"]["satcat_csv"]

ALUMINA_YIELD = float(CFG.get("alumina_kg_per_kg_aluminum", 1.89))
STARLINK_AL_FRACTION = float(CFG.get("aluminum_fraction_of_satellite", 0.7))

REQUIRED_COLUMNS = ("OBJECT_NAME", "OBJECT_TYPE", "DECAY_DATE")
OBJECT_TYPES = ("PAY", "R/B", "DEB", "UNK")


class CatalogError(RuntimeError):
    """The catalogue was fetched but isn't in the shape we can read."""


def ts():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def avg_starlink_mass(mix_key):
    """Weighted average Starlink mass (kg) for the given generation mix."""
    masses, mix = CFG["masses"], CFG[mix_key]
    total_w = sum(max(0.0, mix.get(k, 0.0)) for k in ("v1", "v15", "v2m")) or 1.0
    return sum(max(0.0, mix.get(k, 0.0)) / total_w * masses[k] for k in ("v1", "v15", "v2m"))


def object_type(raw):
    t = (raw or "").strip().upper()
    return t if t in OBJECT_TYPES else "UNK"


def estimate_mass_kg(otype, rcs):
    """Mass estimate for a non-Starlink object, from RCS when it's published."""
    defaults = TOTALS_CFG.get("default_mass_kg", {})
    bounds = TOTALS_CFG.get("mass_bounds_kg", {}).get(otype)
    if not rcs or rcs <= 0:
        return float(defaults.get(otype, defaults.get("UNK", 5)))
    density = float(TOTALS_CFG.get("effective_density_kg_m3", 92.0))
    mass = density * (rcs ** 1.5)          # L = sqrt(RCS); mass ≈ density × L³
    if bounds:
        mass = min(max(mass, float(bounds[0])), float(bounds[1]))
    return mass


def aluminum_fraction(otype):
    fractions = TOTALS_CFG.get("aluminum_fraction", {})
    return float(fractions.get(otype, fractions.get("UNK", 0.5)))


def parse_float(raw):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def parse_year(raw):
    """Leading 4-digit year from a SATCAT date, or None. Tolerates partial dates."""
    text = (raw or "").strip()
    if len(text) < 4 or not text[:4].isdigit():
        return None
    year = int(text[:4])
    return year if 1957 <= year <= datetime.date.today().year else None


def fetch_catalog():
    resp = http_get(SATCAT_CSV, timeout=(10, 180))
    reader = csv.DictReader(io.StringIO(resp.text))
    missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise CatalogError(
            f"SATCAT is missing expected column(s) {missing}; got {reader.fieldnames}"
        )
    return list(reader)


def summarize(rows):
    """Aggregate the catalogue into on-orbit totals and per-year re-entry totals."""
    starlink_active_mass = avg_starlink_mass("mix_active")
    starlink_decayed_mass = avg_starlink_mass("mix_decayed")

    on_orbit = {"starlink_kg": 0.0, "other_kg": 0.0, "starlink_n": 0, "other_n": 0}
    years = {}   # year -> per-bucket kg of re-entered mass and alumina

    for row in rows:
        name = (row.get("OBJECT_NAME") or "").upper()
        is_starlink = "STARLINK" in name
        otype = object_type(row.get("OBJECT_TYPE"))
        decay_year = parse_year(row.get("DECAY_DATE"))

        if is_starlink:
            mass = starlink_decayed_mass if decay_year else starlink_active_mass
            al_fraction = STARLINK_AL_FRACTION
        else:
            mass = estimate_mass_kg(otype, parse_float(row.get("RCS")))
            al_fraction = aluminum_fraction(otype)

        if decay_year is None:
            bucket = "starlink" if is_starlink else "other"
            on_orbit[f"{bucket}_kg"] += mass
            on_orbit[f"{bucket}_n"] += 1
            continue

        alumina = mass * al_fraction * ALUMINA_YIELD
        year = years.setdefault(decay_year, {
            "year": decay_year,
            "starlink_kg": 0.0, "other_kg": 0.0,
            "starlink_alumina_kg": 0.0, "other_alumina_kg": 0.0,
            "starlink_n": 0, "other_n": 0,
        })
        bucket = "starlink" if is_starlink else "other"
        year[f"{bucket}_kg"] += mass
        year[f"{bucket}_alumina_kg"] += alumina
        year[f"{bucket}_n"] += 1

    return on_orbit, [years[y] for y in sorted(years)]


def share(part, whole):
    return round(part / whole, 4) if whole else 0.0


def build_totals(rows):
    on_orbit, by_year = summarize(rows)

    for y in by_year:
        for key in ("starlink_kg", "other_kg", "starlink_alumina_kg", "other_alumina_kg"):
            y[key] = round(y[key], 1)

    total_on_orbit = on_orbit["starlink_kg"] + on_orbit["other_kg"]
    cum_starlink = sum(y["starlink_alumina_kg"] for y in by_year)
    cum_other = sum(y["other_alumina_kg"] for y in by_year)

    # "This year so far" is misleading in January, so the headline delta uses the
    # last complete calendar year.
    complete_years = [y for y in by_year if y["year"] < datetime.date.today().year]
    latest = complete_years[-1] if complete_years else None

    return {
        "generated_at": ts(),
        "catalog_objects": len(rows),
        "on_orbit": {
            "total_kg": round(total_on_orbit, 1),
            "starlink_kg": round(on_orbit["starlink_kg"], 1),
            "other_kg": round(on_orbit["other_kg"], 1),
            "starlink_share": share(on_orbit["starlink_kg"], total_on_orbit),
            "starlink_objects": on_orbit["starlink_n"],
            "other_objects": on_orbit["other_n"],
        },
        "reentry_by_year": by_year,
        "chart_from_year": int(TOTALS_CFG.get("chart_from_year", 2000)),
        "latest_complete_year": latest["year"] if latest else None,
        "latest_year_delta": {
            "reentered_kg_with_starlink": round(latest["starlink_kg"] + latest["other_kg"], 1),
            "reentered_kg_without_starlink": latest["other_kg"],
            "alumina_kg_with_starlink": round(
                latest["starlink_alumina_kg"] + latest["other_alumina_kg"], 1),
            "alumina_kg_without_starlink": latest["other_alumina_kg"],
            "alumina_delta_kg": latest["starlink_alumina_kg"],
            "starlink_share_of_alumina": share(
                latest["starlink_alumina_kg"],
                latest["starlink_alumina_kg"] + latest["other_alumina_kg"]),
        } if latest else None,
        "cumulative_alumina": {
            "with_starlink_kg": round(cum_starlink + cum_other, 1),
            "without_starlink_kg": round(cum_other, 1),
            "delta_kg": round(cum_starlink, 1),
            "starlink_share": share(cum_starlink, cum_starlink + cum_other),
        },
        "assumptions": {
            "note": "SATCAT publishes radar cross-section, not mass. Non-Starlink "
                    "masses are RCS-derived estimates; Starlink objects use the "
                    "generation mass mix in starlink_config.yml.",
            "effective_density_kg_m3": TOTALS_CFG.get("effective_density_kg_m3"),
            "default_mass_kg": TOTALS_CFG.get("default_mass_kg"),
            "mass_bounds_kg": TOTALS_CFG.get("mass_bounds_kg"),
            "aluminum_fraction": TOTALS_CFG.get("aluminum_fraction"),
            "starlink_aluminum_fraction": STARLINK_AL_FRACTION,
            "alumina_yield": ALUMINA_YIELD,
            "starlink_attribution": "Objects whose SATCAT name contains STARLINK. "
                                    "Launch vehicle stages count as other objects.",
        },
        "sources": {"celestrak_satcat_csv": SATCAT_CSV},
    }


def main():
    out_path = DATA / "space_totals.json"
    try:
        rows = fetch_catalog()
    except (FetchError, CatalogError) as err:
        if out_path.exists():
            print(f"SATCAT unavailable ({err}); keeping the previous comparison.",
                  file=sys.stderr)
            return 0
        print(f"SATCAT unavailable ({err}) and no previous comparison to fall back on.",
              file=sys.stderr)
        return 1

    totals = build_totals(rows)
    out_path.write_text(json.dumps(totals, indent=2), encoding="utf-8")

    on_orbit = totals["on_orbit"]
    cum = totals["cumulative_alumina"]
    print(f"Catalogue: {totals['catalog_objects']:,} objects. "
          f"On orbit {on_orbit['total_kg']:,.0f} kg "
          f"({on_orbit['starlink_share'] * 100:.1f}% Starlink). "
          f"Cumulative Al₂O₃ {cum['with_starlink_kg']:,.0f} kg, "
          f"{cum['delta_kg']:,.0f} kg of it from Starlink.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
