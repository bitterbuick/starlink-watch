# Starlink Watch (Cloud Automation)

Fully automatic monitoring of Starlink's environmental, cybersecurity, and astronomical
footprint. No API keys, no paid services — GitHub Actions does everything on a schedule.

**Live site:** [https://bitterbuick.github.io/starlink-watch/](https://bitterbuick.github.io/starlink-watch/)

## How it works (auto-magic)

The `Starlink Daily Digest` workflow runs twice daily (~09:00 and ~17:00 PT) and:

1. **Computes constellation metrics** (`scripts/compute_starlink_metrics.py`)
   — pulls active Starlink elements and confirmed decay records from CelesTrak,
   converts them to mass estimates using the generation mass mix in
   `data/starlink_config.yml`, and derives an upper-bound alumina (Al₂O₃) estimate.
2. **Generates the daily digest** (`scripts/starlink_daily_digest.py`)
   — scans the RSS feeds in `scripts/feeds.yml`, keeps only Starlink-specific
   criticism/risk/event items (keyword filter in `scripts/starlink_utils.py`),
   classifies each into Environmental / Cybersecurity / Astronomical, and writes
   `Starlink Watch/Events/<timestamp> — Starlink Daily Digest.md` plus per-domain
   archive entries. Classification is deterministic keyword scoring — no LLM,
   no external API.
3. **Builds and deploys the static site** (`scripts/build_site.py`)
   — embeds the daily series into interactive SVG charts (hover tooltips,
   range filters, and linear trend projections rendered client-side; no
   charting libraries) and publishes to GitHub Pages.

There is nothing to configure. Fork it, enable Actions and Pages, and it runs.

## The story the data tells

Starlink satellites live about five years, then deorbit and burn up completely.
A satellite is largely aluminum; re-entry ablation converts that aluminum into
aluminum oxide (alumina) nanoparticles deposited at 50–85 km altitude, which settle
into the stratosphere — the ozone layer — over years to decades. Alumina surfaces
catalyze chlorine activation, the same chemistry behind polar ozone loss.

The site's four charts follow the mass through that pipeline:

| Step | Chart | Meaning |
|------|-------|---------|
| 1 | Active satellites | Launch cadence; today's count is the re-entry rate ~5 years out |
| 2 | On-orbit mass | The atmosphere's future intake — all of it is scheduled to burn up |
| 3 | Re-entered mass | Mass already delivered to the upper atmosphere |
| 4 | Al₂O₃ estimate | Upper-bound alumina injected (Al fraction × 1.89 kg Al₂O₃ per kg Al) |

Key research: Murphy et al. 2023 (PNAS) found spacecraft metals in ~10% of
stratospheric aerosol particles; Ferreira et al. 2024 (GRL) modeled ~30 kg of alumina
nanoparticles per ~250 kg satellite and projected megaconstellation-era injection well
above the natural meteoric background. See the Environmental archive for the full
literature trail.

## Local use

```bash
pip install -r requirements.txt
python scripts/compute_starlink_metrics.py
python scripts/starlink_daily_digest.py --force   # --dry-run to preview classification
python scripts/build_site.py                       # writes site/index.html
python -m unittest discover tests                  # run filter tests
```

The repo doubles as an Obsidian vault — digests land in `Starlink Watch/Events/` and
rolling archives in `Starlink Watch/Archive/` (install Obsidian Git to auto-pull).

All mass/alumina assumptions are tunable in `data/starlink_config.yml`.
