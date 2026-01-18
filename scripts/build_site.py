#!/usr/bin/env python3
# Starlink Watch — static site builder with inline citations
import json, html, datetime
from pathlib import Path
import re

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


def find_digest_page():
    preferred = [
        REPO / "index.html",
        REPO / "index.md",
        REPO / "README.md",
    ]
    for cand in preferred:
        if cand.exists():
            txt = cand.read_text(encoding="utf-8")
            if "<section class=\"starlink-digest\">" in txt:
                return cand

    for cand in REPO.rglob("*.md"):
        if "starlink-digest" not in cand.read_text(encoding="utf-8"):
            continue
        return cand
    return None


def parse_incidents_from_html(txt):
    incidents = []
    m = re.search(r"<h3>Incident Timeline</h3>.*?<ul class=\"digest-timeline\">(.*?)</ul>", txt, re.S)
    if not m:
        return incidents
    for raw in re.findall(r"<li>\s*(.*?)\s*</li>", m.group(1), re.S):
        cleaned = re.sub(r"\s+", " ", raw.strip())
        dm = re.match(r"<strong>(\d{4}-\d{2}-\d{2})</strong> — (.*)", cleaned)
        if dm:
            incidents.append({"date": dm.group(1), "summary": dm.group(2).strip()})
    incidents.sort(key=lambda x: x["date"], reverse=True)
    return incidents


def parse_sources_from_html(txt):
    sources = []
    m = re.search(r"<h3>Data Sources</h3>.*?<ul>(.*?)</ul>", txt, re.S)
    if not m:
        return sources
    for raw in re.findall(r"<li>\s*(.*?)\s*</li>", m.group(1), re.S):
        cleaned = re.sub(r"\s+", " ", raw.strip())
        link = re.search(r'href=\"([^\"]+)\"', cleaned)
        url = link.group(1) if link else ""
        label_desc = re.sub(r"<[^>]+>", "", cleaned)
        if " — " in label_desc:
            label, desc = label_desc.split(" — ", 1)
        elif "-" in label_desc:
            label, desc = label_desc.split("-", 1)
        else:
            label, desc = label_desc, ""
        sources.append({"label": label.strip(), "description": desc.strip(), "url": url})
    return sources


def ensure_incidents():
    p = DATA / "incidents.json"
    def dedupe(items):
        seen = set()
        out = []
        for inc in items:
            key = (inc.get("date", ""), inc.get("summary", ""))
            if key in seen:
                continue
            seen.add(key)
            out.append(inc)
        return out

    if p.exists():
        incidents = json.loads(p.read_text(encoding="utf-8"))
    else:
        digest_page = find_digest_page()
        incidents = []
        if digest_page:
            incidents = parse_incidents_from_html(digest_page.read_text(encoding="utf-8"))

    incidents = dedupe(incidents)
    incidents.sort(key=lambda x: x.get("date", ""), reverse=True)
    p.write_text(json.dumps(incidents, indent=2), encoding="utf-8")
    return incidents


def ensure_sources():
    p = DATA / "sources.json"
    if p.exists():
        sources = json.loads(p.read_text(encoding="utf-8"))
        p.write_text(json.dumps(sources, indent=2), encoding="utf-8")
        return sources

    digest_page = find_digest_page()
    sources = []
    if digest_page:
        sources = parse_sources_from_html(digest_page.read_text(encoding="utf-8"))
    p.write_text(json.dumps(sources, indent=2), encoding="utf-8")
    return sources


def normalize_sort_key(raw_date: str) -> str:
    """Best-effort YYYY-MM(-DD) sort key from the leading token of raw_date."""
    token = raw_date.split()[0].split("→")[0].split("->")[0].strip()
    full = re.match(r"(\d{4}-\d{2}-\d{2})", token)
    if full:
        return full.group(1)
    partial = re.match(r"(\d{4}-\d{2})", token)
    if partial:
        return partial.group(1)
    return ""


def parse_archive_file(domain: str, path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    description = ""
    entries = []

    for ln in lines:
        stripped = ln.strip()
        if not description and stripped.startswith("*") and stripped.endswith("*"):
            description = stripped.strip("*").strip()

        if not stripped.startswith("- "):
            continue
        item = stripped[2:].strip()
        if item == "No new items.":
            continue
        if "|" not in item:
            continue

        raw_date, remainder = item.split("|", 1)
        raw_date = raw_date.strip()
        remainder = remainder.strip()

        m = re.search(r"\*\*(.+?)\*\*", remainder)
        if not m:
            continue
        title = m.group(1).strip()
        after_title = remainder[m.end():].strip()

        urls = re.findall(r"https?://\S+", after_title)
        primary_url = urls[0] if urls else ""

        rest = re.sub(r"https?://\S+", "", after_title)
        rest = re.sub(r"\s*\|\s*", " ", rest)
        rest = " ".join(rest.split()).strip()
        rest = rest.strip("— ").strip()

        entries.append(
            {
                "domain": domain,
                "date_display": raw_date,
                "date_sort_key": normalize_sort_key(raw_date),
                "title": title,
                "rest": rest,
                "primary_url": primary_url,
            }
        )

    return {"domain": domain, "description": description, "entries": entries}


def load_archives():
    archives = []
    for name in ["Environmental", "Cybersecurity", "Astronomical"]:
        path = ARCH / f"{name}.md"
        if path.exists():
            archives.append(parse_archive_file(name, path))
    return archives


def render_global_archive(archives):
    all_entries = []
    for arc in archives:
        all_entries.extend(arc.get("entries", []))

    deduped = []
    seen = set()
    for idx, entry in enumerate(all_entries):
        key = (entry.get("domain", ""), entry.get("date_display", ""), entry.get("title", ""), entry.get("primary_url", ""))
        if key in seen:
            continue
        seen.add(key)
        entry["_orig_idx"] = idx
        deduped.append(entry)

    with_key = [e for e in deduped if e.get("date_sort_key")]
    without_key = [e for e in deduped if not e.get("date_sort_key")]

    with_key.sort(key=lambda e: (e.get("date_sort_key", ""), e.get("_orig_idx", 0)), reverse=True)

    ordered = with_key + without_key

    items = []
    for e in ordered:
        date_disp = html.escape(e.get("date_display", ""))
        domain = html.escape(e.get("domain", ""))
        title = html.escape(e.get("title", ""))
        rest = html.escape(e.get("rest", ""))
        title_html = title
        if e.get("primary_url"):
            url = html.escape(e["primary_url"])
            title_html = f"<a href=\"{url}\" target=\"_blank\" rel=\"noopener noreferrer\">{title}</a>"
        rest_html = f" — {rest}" if rest else ""
        items.append(
            f"      <li>\n        <strong>{date_disp}</strong> — <span class=\"archive-domain\">{domain}</span> — {title_html}{rest_html}\n      </li>"
        )

    return """
  <section class="starlink-archive">
    <h2>Global Archive Timeline</h2>
    <p>
      Consolidated record of notable Starlink-related environmental, cybersecurity, and astronomical items, drawn from the per-domain archive files.
    </p>
    <ul class="archive-timeline">
{items}
    </ul>
  </section>""".format(items="\n".join(items))


def render_domain_archives(archives):
    sections = []
    for arc in archives:
        domain = arc.get("domain", "")
        desc = html.escape(arc.get("description", ""))
        slug = domain.lower()
        items = []
        for e in arc.get("entries", []):
            date_disp = html.escape(e.get("date_display", ""))
            title = html.escape(e.get("title", ""))
            rest = html.escape(e.get("rest", ""))
            title_html = title
            if e.get("primary_url"):
                url = html.escape(e["primary_url"])
                title_html = f"<a href=\"{url}\" target=\"_blank\" rel=\"noopener noreferrer\">{title}</a>"
            rest_html = f" — {rest}" if rest else ""
            items.append(f"      <li>\n        <strong>{date_disp}</strong> | {title_html}{rest_html}\n      </li>")

        sections.append(
            """
  <section class="starlink-domain-archive">
    <h2>{domain} — Archive</h2>
    <p>{desc}</p>
    <ul class="archive-list archive-list-{slug}">
{items}
    </ul>
  </section>""".format(domain=html.escape(domain), desc=desc, slug=slug, items="\n".join(items))
        )

    return "\n\n".join(sections)


def render_timeline_items(incidents, indent="      "):
    nested = indent + "  "
    items = []
    for inc in incidents:
        date = html.escape(inc.get("date", ""))
        summary = html.escape(inc.get("summary", ""))
        items.append(
            f"{indent}<li>\n{nested}<strong>{date}</strong> — {summary}\n{indent}</li>"
        )
    items.append(
        f"{indent}<li>\n{nested}<strong>Most recent confirmed Starlink re-entry</strong> — The latest Starlink re-entry record in the CelesTrak/SATCAT “decayed objects” dataset remains unchanged relative to the prior digest unless otherwise noted above.\n{indent}</li>"
    )
    return "\n".join(items)


def update_page_timeline(page_path, incidents):
    txt = page_path.read_text(encoding="utf-8")
    m = re.search(r"(?P<indent>\s*)<ul class=\"digest-timeline\">.*?</ul>", txt, re.S)
    if not m:
        return False
    indent = m.group("indent")
    li_indent = indent + "  "
    new_ul = f"{indent}<ul class=\"digest-timeline\">\n{render_timeline_items(incidents, indent=li_indent)}\n{indent}</ul>"
    updated = txt[: m.start()] + new_ul + txt[m.end():]
    if updated != txt:
        page_path.write_text(updated, encoding="utf-8")
        return True
    return False

def chart(df, title, out_png):
    if df.empty:
        # write a placeholder so <img> doesn't 404
        plt.figure(figsize=(10, 4.5))
        plt.text(0.5, 0.5, "No data yet", ha="center", va="center")
        plt.axis("off")
        plt.tight_layout()
        plt.savefig(out_png, dpi=160)
        plt.close()
        return
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    plt.figure(figsize=(10, 4.5))
    plt.plot(df["date"], df["value"])
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out_png, dpi=160)
    plt.close()

# ---------- build ----------
def build():
    met = load_metrics() or {}
    src = met.get("sources", {})
    src_gp = src.get("celestrak_gp_csv", "https://celestrak.org/NORAD/elements/")
    src_decayed = src.get("celestrak_decayed", "https://celestrak.org/satcat/decayed-with-last.php")

    incidents = ensure_incidents()
    sources = ensure_sources()
    archives = load_archives()

    timeline_html = render_timeline_items(incidents)
    global_archive_html = render_global_archive(archives)
    domain_archives_html = render_domain_archives(archives)

    digest_page = find_digest_page()
    if digest_page:
        update_page_timeline(digest_page, incidents)

    source_items = []
    for src_obj in sources:
        label = html.escape(src_obj.get("label", ""))
        desc = html.escape(src_obj.get("description", ""))
        url = src_obj.get("url", "")
        label_html = label
        if url:
            label_html = f"<a href=\"{html.escape(url)}\" target=\"_blank\" rel=\"noopener noreferrer\">{label}</a>"
        source_items.append(
            f"""
      <li>
        <strong>{label_html}</strong> — {desc}
      </li>"""
        )
    sources_html = "".join(source_items)

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
  .grid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); }}
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
      {timeline_html}
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
      {sources_html}
    </ul>
    <p>
      All assumptions and mass-mix parameters remain editable in <code>data/starlink_config.yml</code>, and charts on
      this site are derived directly from these datasets and configuration values on each run.
    </p>

  </section>

{global_archive_html}

{domain_archives_html}

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
    .starlink-archive {{
      margin-top: 2rem;
    }}
    .archive-timeline {{
      list-style: none;
      padding-left: 0;
    }}
    .archive-timeline li {{
      margin-bottom: 0.5rem;
    }}
    .archive-domain {{
      font-style: italic;
      opacity: 0.85;
    }}
    .starlink-domain-archive {{
      margin-top: 2rem;
    }}
    .starlink-domain-archive ul {{
      list-style: none;
      padding-left: 0;
    }}
    .starlink-domain-archive li {{
      margin-bottom: 0.4rem;
    }}
  </style>
</main>

<footer><div class="wrap muted">
  Starlink-only; prioritizes criticisms, risks, and concrete events. Charts update on each run.
</div></footer>
</body></html>"""
    (SITE / "index.html").write_text(page, encoding="utf-8")

if __name__ == "__main__":
    build()
