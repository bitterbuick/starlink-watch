#!/usr/bin/env python3
# Starlink Watch — static site builder with inline citations
import json, html, datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
import pandas as pd

REPO   = Path(__file__).resolve().parents[1]
VAULT  = REPO / "Starlink Watch"
EVENTS = VAULT / "Events"
ARCH   = VAULT / "Archive"
DATA   = REPO / "data"
SITE   = REPO / "site"
ASSETS = SITE / "assets"
SITE.mkdir(exist_ok=True, parents=True)
ASSETS.mkdir(exist_ok=True, parents=True)

# ---------- helpers ----------
def load_metrics():
    p = DATA / "metrics.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

def load_series(name):
    p = DATA / "series" / f"{name}.json"
    if not p.exists():
        return pd.DataFrame({"date": [], "value": []})
    ser = json.loads(p.read_text(encoding="utf-8"))
    return pd.DataFrame(ser)

def chart(df, title, out_png):
    if df.empty:
        # write a placeholder so <img> doesn't 404
        plt.figure(figsize=(8,3))
        plt.text(0.5, 0.5, "No data yet", ha="center", va="center")
        plt.axis("off")
        plt.tight_layout()
        plt.savefig(out_png, dpi=140)
        plt.close()
        return
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    plt.figure(figsize=(8,3))
    plt.plot(df["date"], df["value"])
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out_png, dpi=140)
    plt.close()

# ---------- build ----------
def build():
    met = load_metrics() or {}
    src = met.get("sources", {})
    src_gp = src.get("celestrak_gp_csv", "https://celestrak.org/NORAD/elements/")
    src_decayed = src.get("celestrak_decayed", "https://celestrak.org/satcat/decayed-with-last.php")

    # charts (saved to /site/assets)
    chart(load_series("active_count"),      "Active Starlink satellites (count)", ASSETS/"active.png")
    chart(load_series("on_orbit_mass_kg"),  "Estimated on-orbit mass (kg)",       ASSETS/"onorbit.png")
    chart(load_series("reentered_mass_kg"), "Estimated re-entered mass (kg)",     ASSETS/"reentry.png")
    chart(load_series("alumina_kg"),        "Estimated Al₂O₃ formed (kg)",        ASSETS/"alumina.png")

    built = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # tiles with inline citations (ⓘ)
    tiles = ""
    if met:
        tiles = f"""
        <div class="tiles">
          <div class="tile">
            <div class="k">{met.get('active_count',0):,}</div>
            <div class="t">Active Starlink
              <a class="info" href="{html.escape(src_gp)}" target="_blank" title="Source: CelesTrak Starlink GP/CSV">ⓘ</a>
            </div>
          </div>
          <div class="tile">
            <div class="k">{met.get('decayed_total',0):,}</div>
            <div class="t">Total decayed
              <a class="info" href="{html.escape(src_decayed)}" target="_blank" title="Source: CelesTrak SATCAT recently decayed">ⓘ</a>
            </div>
          </div>
          <div class="tile">
            <div class="k">{met.get('on_orbit_mass_kg',0):,}</div>
            <div class="t">On-orbit mass (kg)
              <a class="info" href="{html.escape(src_gp)}" target="_blank" title="Derived from CelesTrak active counts × generation mass mix (see data/starlink_config.yml)">ⓘ</a>
            </div>
          </div>
          <div class="tile">
            <div class="k">{met.get('reentered_mass_kg',0):,}</div>
            <div class="t">Re-entered mass (kg)
              <a class="info" href="{html.escape(src_decayed)}" target="_blank" title="Derived from accumulated Starlink decays × generation mass mix (see data/starlink_config.yml)">ⓘ</a>
            </div>
          </div>
          <div class="tile">
            <div class="k">{met.get('alumina_kg',0):,}</div>
            <div class="t">Al₂O₃ estimate (kg)
              <a class="info" href="#" title="Proxy: aluminum fraction × 1.89 kg Al₂O₃ per kg Al (upper-bound stoichiometry). Tune in data/starlink_config.yml.">ⓘ</a>
            </div>
          </div>
        </div>
        """

    # page HTML
    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Starlink Watch — Metrics & Digest</title>
<style>
  :root {{ --bg:#0b1220; --fg:#e6edf3; --muted:#9fb0bd; --card:#0f172a; --ring:#1f2937; --accent:#60a5fa; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.55 ui-sans-serif,system-ui,Segoe UI,Roboto; }}
  header, footer {{ padding:22px 16px; border-bottom:1px solid var(--ring); }}
  footer {{ border-top:1px solid var(--ring); border-bottom:none; }}
  .wrap {{ max-width:1150px; margin:0 auto; padding:0 16px; }}
  h1,h2,h3 {{ margin:0 0 12px; }}
  .muted {{ color:var(--muted); font-size:.92em }}
  .card {{ background:var(--card); border-radius:14px; padding:18px 20px; box-shadow:0 6px 24px #0008, inset 0 1px 0 #ffffff0f; }}
  .grid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); }}
  .tiles {{ display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); margin:14px 0 4px; }}
  .tile {{ background:#0d1528; border:1px solid #15233b; border-radius:12px; padding:12px 14px; }}
  .tile .k {{ font-size:28px; font-weight:700 }}
  .tile .t {{ color:var(--muted); font-size:13px }}
  a {{ color:var(--accent); text-decoration:none }} a:hover {{ text-decoration:underline }}
  a.info {{ font-weight:700; margin-left:6px; text-decoration:none; border-bottom:1px dotted #8ab4ff; cursor:help }}
  img.chart {{ width:100%; height:auto; border-radius:10px; background:#0d1528; border:1px solid #15233b; padding:6px; }}
  ul {{ margin:10px 0 0 20px }}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>Starlink Watch — Metrics & Digest</h1>
    <div class="muted">Built {html.escape(datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))}</div>
  </div>
</header>

<main class="wrap" style="padding:22px 0 36px">
  <section class="card">
    <h2>Starlink metrics</h2>
    {tiles}
    <div class="grid" style="margin-top:8px">
      <div class="card">
        <h3>Active satellites
          <a class="info" href="{html.escape(src_gp)}" target="_blank" title="CelesTrak Starlink group (GP/CSV)">ⓘ</a>
        </h3>
        <img class="chart" src="assets/active.png" alt="">
      </div>
      <div class="card">
        <h3>On-orbit mass (kg)
          <a class="info" href="{html.escape(src_gp)}" target="_blank" title="Derived from active counts × generation masses (configurable)">ⓘ</a>
        </h3>
        <img class="chart" src="assets/onorbit.png" alt="">
      </div>
      <div class="card">
        <h3>Re-entered mass (kg)
          <a class="info" href="{html.escape(src_decayed)}" target="_blank" title="Accumulated Starlink decays (CelesTrak SATCAT) × generation masses">ⓘ</a>
        </h3>
        <img class="chart" src="assets/reentry.png" alt="">
      </div>
      <div class="card">
        <h3>Al₂O₃ estimate (kg)
          <a class="info" href="#" title="Al fraction × 1.89 kg Al₂O₃ per kg Al (upper-bound stoichiometry); tune in data/starlink_config.yml">ⓘ</a>
        </h3>
        <img class="chart" src="assets/alumina.png" alt="">
      </div>
    </div>
    <p class="muted">
      Assumptions and mass mix are editable in <code>data/starlink_config.yml</code>.
      Metrics are derived from public datasets; see citations below.
    </p>
  </section>

  <section class="starlink-digest">

    <!-- Header / Lede -->
    <h2>Latest Digest</h2>
    <h3>Starlink Daily Digest — 2025-12-09</h3>

    <p>
      No new Starlink-specific environmental, cybersecurity, or astronomical developments were identified on
      <strong>2025-12-09</strong> during routine cross-domain monitoring. The constellation’s risk posture for this cycle
      appears stable within the limits of currently available public data.
    </p>

    <hr />

    <!-- Key Findings -->
    <h3>Key Findings</h3>

    <div class="digest-key-findings">

      <article class="digest-card">
        <h4>Environmental</h4>
        <p><strong>Status:</strong> No Starlink-specific changes detected.</p>
        <p>
          Recent checks of atmospheric re-entry logs, orbital decay catalogs, and regulatory bulletins showed no newly
          confirmed Starlink re-entries, debris notices, or enforcement actions since the prior digest. Within the
          constraints of available data, the cumulative alumina load and debris profile remain consistent with previous
          cycles, suggesting no short-term deviation from the modeled environmental risk trajectory.
        </p>
      </article>

      <article class="digest-card">
        <h4>Cybersecurity</h4>
        <p><strong>Status:</strong> No Starlink-specific changes detected.</p>
        <p>
          Reviews of vulnerability disclosures, CERT/CC and national CERT feeds, vendor advisories, and open
          threat-intelligence reporting produced no fresh references to Starlink user terminals, ground infrastructure,
          or associated supply-chain compromises. The absence of new public advisories this cycle indicates a steady
          threat surface rather than evidence of safety, and continued monitoring remains warranted given Starlink’s role
          in critical connectivity.
        </p>
      </article>

      <article class="digest-card">
        <h4>Astronomical</h4>
        <p><strong>Status:</strong> No Starlink-specific changes detected.</p>
        <p>
          Optical streak reports, radio-frequency interference notes, and observatory mitigation updates showed no new
          Starlink-attributed survey-contamination events or RFI anomalies since the last check. Existing mitigation
          practices and survey workarounds appear unchanged, leaving the overall astronomical impact profile similar to
          prior assessments for this short interval.
        </p>
      </article>

    </div>

    <hr />

    <!-- Summary Table -->
    <h3>Summary of Changes</h3>

    <table class="digest-summary">
      <thead>
        <tr>
          <th>Domain</th>
          <th>Updates Detected</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Environmental</td>
          <td>No</td>
        </tr>
        <tr>
          <td>Cybersecurity</td>
          <td>No</td>
        </tr>
        <tr>
          <td>Astronomical</td>
          <td>No</td>
        </tr>
      </tbody>
    </table>

    <hr />

    <!-- Incident Timeline (running history; DO NOT delete older items on future runs) -->
    <h3>Incident Timeline</h3>

    <ul class="digest-timeline">
      <!-- Always insert the newest digest entry at the TOP of this list on future updates.
           Older items below must never be removed so the timeline remains a running history. -->

      <li>
        <strong>2025-12-09</strong> — Routine monitoring completed. No Starlink-specific incidents, re-entry confirmations
        or regulatory actions were identified across environmental, cybersecurity, or astronomical sources.
      </li>
      <li>
        <strong>2025-12-08</strong> — Previous digest also recorded no new Starlink incidents following cross-checks of
        re-entry notices, cybersecurity advisories, and observatory reporting.
      </li>
      <li>
        <strong>Most recent confirmed Starlink re-entry</strong> — The latest Starlink re-entry record in the
        CelesTrak/SATCAT “decayed objects” dataset remains unchanged relative to the prior digest; no newer decays have
        been attributed to Starlink since that entry.
      </li>
    </ul>

    <p class="digest-note">
      Quiet days are logged explicitly to preserve an auditable history of checks, distinguish true low-activity periods
      from monitoring gaps, and support future trend analysis.
    </p>

    <hr />

    <!-- Methodology & Rationale -->
    <h2>Methodology &amp; Rationale</h2>

    <h3>Why These Domains Are Tracked</h3>
    <p>
      This project tracks three classes of risk where a constellation as large as Starlink can generate outsized
      systemic effects:
    </p>
    <ul>
      <li><strong>Environmental</strong> — Atmospheric re-entries, alumina production, debris generation, and any regulatory or scientific findings relating to climate and ozone impacts.</li>
      <li><strong>Cybersecurity</strong> — Vulnerabilities, exploitation, and operational security issues involving user terminals, ground infrastructure, or Starlink’s role in high-value networks.</li>
      <li><strong>Astronomical</strong> — Optical streaks, survey contamination, radio interference, and mitigation measures affecting professional observatories and large survey projects.</li>
    </ul>
    <p>
      The goal is not to predict every outcome but to maintain a disciplined, source-driven record of developments that
      could materially change the constellation’s risk profile over time.
    </p>

    <h3>Environmental Modeling</h3>
    <p>
      Environmental assessments combine object counts, re-entry events, and simple alumina mass estimates:
    </p>
    <ul>
      <li>
        <strong>Object and decay tracking</strong> rely on CelesTrak Starlink GP/CSV files for active elements and SATCAT
        “recently decayed” lists for confirmed re-entries.
      </li>
      <li>
        <strong>Alumina estimates</strong> use a generation mass mix defined in
        <code>data/starlink_config.yml</code>, encoding assumptions about per-satellite mass, aluminum content, and the
        fraction converted to alumina during re-entry. These assumptions are drawn from published re-entry and
        spacecraft-material studies and are intentionally conservative.
      </li>
      <li>
        <strong>Cumulative impact</strong> is tracked as a running total of estimated alumina injected into the upper
        atmosphere by confirmed Starlink re-entries, to make the approximate scale and growth of material deposition
        explicit rather than abstract.
      </li>
    </ul>
    <p>
      This matters because alumina can alter radiative forcing and interact with ozone chemistry. Even with wide error
      bars, documenting the plausible mass and slope over time is more informative than relying on one-off marketing
      claims or isolated estimates.
    </p>

    <h3>Cybersecurity Monitoring</h3>
    <p>
      Cyber assessments focus on how Starlink terminals and infrastructure appear in public security reporting:
    </p>
    <ul>
      <li>
        <strong>Primary inputs</strong> include CERT/CC and national CERT advisories, major vendor bulletins, and
        reputable threat-intelligence publications.
      </li>
      <li>
        <strong>Scope</strong> is limited to issues that explicitly reference Starlink hardware, firmware, or
        infrastructure, plus clearly linked supply-chain or satellite-control vulnerabilities.
      </li>
      <li>
        <strong>Interpretation</strong> emphasizes trend and posture: new advisories are treated as signals of an exposed
        or actively targeted attack surface; quiet periods constrain what can be concluded from public data.
      </li>
    </ul>
    <p>
      Because Starlink is being woven into critical communications, battlefield connectivity, and research networks, even
      incremental vulnerability disclosures are treated as important signals rather than routine patch notes.
    </p>

    <h3>Astronomical Impact Assessment</h3>
    <p>
      Astronomical impact monitoring tracks how Starlink appears in the literature and reporting on sky surveys:
    </p>
    <ul>
      <li><strong>Optical effects</strong> — satellite streaks in wide-field survey images, changes in streak frequency, and mitigation tactics such as avoidance windows or exposure adjustments.</li>
      <li><strong>Radio-frequency interference (RFI)</strong> — observatory notes and survey documentation describing interference from satellite constellations in relevant bands.</li>
      <li><strong>Mitigation updates</strong> — darker coatings, attitude changes, or coordination protocols that alter expected long-term impact.</li>
    </ul>
    <p>
      Survey science depends on clean, statistically stable skies. A constellation that injects structured noise into
      those datasets changes both the cost and feasibility of key astronomical programs.
    </p>

    <h3>Why “Quiet” Days Are Still Logged</h3>
    <p>
      Each digest date is recorded even when no new Starlink-specific developments are found because:
    </p>
    <ul>
      <li>It provides a continuous audit trail of which sources were checked and when.</li>
      <li>It distinguishes genuine low-activity periods from monitoring gaps.</li>
      <li>It allows future researchers to correlate bursts of activity with documented baselines.</li>
    </ul>
    <p>
      A “no change” entry is therefore treated as a real data point rather than an empty placeholder.
    </p>

    <hr />

    <!-- Data Sources -->
    <h3>Data Sources</h3>
    <p>
      This digest draws from the following public datasets and model assumptions:
    </p>
    <ul>
      <li>
        <strong>CelesTrak Starlink GP/CSV</strong> — Active Starlink elements, orbital parameters, and counts used to
        understand constellation scale and decay eligibility.
      </li>
      <li>
        <strong>CelesTrak SATCAT – Recently Decayed</strong> — Confirmed decay events, including Starlink entries, used
        to timestamp and tally re-entries.
      </li>
      <li>
        <strong>Vulnerability and advisory feeds</strong> (CERT/CC, national CERTs, vendor bulletins) — Publicly disclosed
        vulnerabilities or incidents referencing Starlink user terminals or supporting infrastructure.
      </li>
      <li>
        <strong>Astronomical reports and RFI notes</strong> — Observatory mitigation reports, optical streak surveys, and
        radio-interference summaries that mention Starlink or similar constellations.
      </li>
      <li>
        <strong>Generation mass mix and alumina assumptions</strong> — Parameters defined in
        <code>data/starlink_config.yml</code> for satellite mass, aluminum fraction, and alumina conversion used in
        environmental calculations.
      </li>
    </ul>
    <p>
      All assumptions and mass-mix parameters remain editable in <code>data/starlink_config.yml</code>, and charts on
      this site are derived directly from these datasets and configuration values on each run.
    </p>

  </section>

  <!-- Optional minimal styling hooks (you may move these into the main CSS file) -->
  <style>
    .starlink-digest {{ margin-top: 1.5rem; }}
    .digest-key-findings {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 1rem;
    }}
    .digest-card {{
      padding: 1rem;
      border-radius: 0.5rem;
      background-color: rgba(255, 255, 255, 0.02);
      border: 1px solid rgba(255, 255, 255, 0.06);
    }}
    .digest-summary {{
      width: 100%;
      border-collapse: collapse;
    }}
    .digest-summary th,
    .digest-summary td {{
      border: 1px solid rgba(255, 255, 255, 0.15);
      padding: 0.5rem 0.75rem;
      text-align: left;
    }}
    .digest-timeline {{ list-style: disc; padding-left: 1.5rem; }}
    .digest-note {{ font-size: 0.9rem; opacity: 0.85; }}
  </style>
</main>

<footer><div class="wrap muted">
  Starlink-only; prioritizes criticisms, risks, and concrete events. Charts update on each run.
</div></footer>
</body></html>"""
    (SITE / "index.html").write_text(page, encoding="utf-8")

if __name__ == "__main__":
    build()
