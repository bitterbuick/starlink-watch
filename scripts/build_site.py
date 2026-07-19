#!/usr/bin/env python3
"""Starlink Watch — static site builder.

Reads data/ (metrics, series, incidents, sources) and the vault archives, and
writes site/index.html. Charts are interactive inline SVG rendered client-side
from embedded series data — no matplotlib/pandas, stdlib only.
"""
import datetime
import html
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VAULT = REPO / "Starlink Watch"
EVENTS = VAULT / "Events"
ARCH = VAULT / "Archive"
DATA = REPO / "data"
SITE = REPO / "site"

# Colors validated (CVD + contrast) against the dark card surface in this order.
CHART_SPECS = [
    {
        "key": "active_count",
        "step": 1,
        "title": "Active satellites",
        "unit": "",
        "color": "#3987e5",
        "caption": "On-orbit count from CelesTrak GP data. With a ~5-year design life, "
                   "today's count previews the re-entry rate five years out.",
        "source": "gp",
        "info_tip": "CelesTrak Starlink group (GP/CSV)",
    },
    {
        "key": "on_orbit_mass_kg",
        "step": 2,
        "title": "On-orbit mass (kg)",
        "unit": "kg",
        "color": "#008300",
        "caption": "Count × generation mass mix (v1.0 ≈ 260 kg, v1.5 ≈ 295 kg, v2 Mini ≈ 730 kg). "
                   "All of it is scheduled to burn up — a backlog, not a steady state.",
        "source": "gp",
        "info_tip": "Active counts × generation mass mix (configurable)",
    },
    {
        "key": "reentered_mass_kg",
        "step": 3,
        "title": "Re-entered mass (kg)",
        "unit": "kg",
        "color": "#9085e9",
        "caption": "Cumulative confirmed re-entries (CelesTrak SATCAT) × mass mix — "
                   "mass already delivered to the upper atmosphere as vapor and particles.",
        "cumulative": True,
        "source": "decayed",
        "info_tip": "Accumulated Starlink decays × generation mass mix",
    },
    {
        "key": "alumina_kg",
        "step": 4,
        "title": "Al₂O₃ estimate (kg)",
        "unit": "kg",
        "color": "#d95926",
        "caption": "Upper bound: re-entered kg × 0.70 aluminum fraction × 1.89 kg Al₂O₃ per kg Al. "
                   "Alumina nanoparticles are the ozone link.",
        "cumulative": True,
        "source": "decayed",
        "info_tip": "Al fraction × 1.89 kg Al₂O₃ per kg Al (upper-bound stoichiometry); "
                    "tune in data/starlink_config.yml",
    },
]


# ---------- data loading ----------
def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def load_series(key):
    """Daily series as sorted [{date, value}]; last value wins on duplicate dates."""
    by_date = {}
    for p in load_json(DATA / "series" / f"{key}.json", []):
        by_date[p["date"]] = p["value"]
    return [{"date": d, "value": by_date[d]} for d in sorted(by_date)]


def delta_30d(series):
    """Change vs the latest point at least 30 days old (or the oldest point)."""
    if len(series) < 2:
        return None
    last = series[-1]
    cutoff = (datetime.date.fromisoformat(last["date"]) - datetime.timedelta(days=30)).isoformat()
    base = series[0]
    for p in series:
        if p["date"] > cutoff:
            break
        base = p
    if base["date"] == last["date"]:
        return None
    return last["value"] - base["value"]


def normalize_sort_key(raw_date):
    """Best-effort YYYY-MM(-DD) sort key from the leading token of raw_date."""
    token = raw_date.split()[0].split("→")[0].split("->")[0].strip()
    m = re.match(r"(\d{4}-\d{2}(-\d{2})?)", token)
    return m.group(1) if m else ""


def parse_archive_file(domain, path):
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
        if item == "No new items." or "|" not in item:
            continue

        raw_date, remainder = (s.strip() for s in item.split("|", 1))
        m = re.search(r"\*\*(.+?)\*\*", remainder)
        if not m:
            continue
        title = m.group(1).strip()
        after_title = remainder[m.end():].strip()

        urls = re.findall(r"https?://\S+", after_title)
        rest = re.sub(r"https?://\S+", "", after_title)
        rest = re.sub(r"\s*\|\s*", " ", rest)
        rest = " ".join(rest.split()).strip("— ").strip()

        entries.append({
            "domain": domain,
            "date_display": raw_date,
            "date_sort_key": normalize_sort_key(raw_date),
            "title": title,
            "rest": rest,
            "primary_url": urls[0] if urls else "",
        })

    return {"domain": domain, "description": description, "entries": entries}


def load_archives():
    archives = []
    for name in ("Environmental", "Cybersecurity", "Astronomical"):
        path = ARCH / f"{name}.md"
        if path.exists():
            archives.append(parse_archive_file(name, path))
    return archives


def load_latest_digest():
    """Parsed fields from the most recent event file, or None."""
    files = sorted(EVENTS.glob("*.md"), reverse=True) if EVENTS.exists() else []
    if not files:
        return None
    latest = files[0]
    text = latest.read_text(encoding="utf-8")

    def section(header):
        m = re.search(rf"### {header}\s*\n(.*?)(?=\n###|\n## |\Z)", text, re.S)
        return m.group(1).strip() if m else ""

    def update_flag(domain):
        m = re.search(rf"\| {domain}\s*\| (Yes|No)", text, re.I)
        return m.group(1) if m else "No"

    date = re.search(r"## Starlink Daily Digest — (\S+)", text)
    return {
        "date": date.group(1) if date else latest.stem[:10],
        "sections": [
            (name, section(name), update_flag(name))
            for name in ("Environmental", "Cybersecurity", "Astronomical")
        ],
    }


# ---------- rendering ----------
def esc(s):
    return html.escape(s)


def entry_title_html(e):
    title = esc(e["title"])
    if e["primary_url"]:
        return f'<a href="{esc(e["primary_url"])}" target="_blank" rel="noopener noreferrer">{title}</a>'
    return title


def entry_li(e, show_domain=False):
    rest = f' — {esc(e["rest"])}' if e["rest"] else ""
    domain = ""
    if show_domain:
        domain = (f' — <span class="archive-domain archive-domain-{e["domain"].lower()}">'
                  f'{esc(e["domain"])}</span> —')
    sep = "" if show_domain else " |"
    return (f'      <li><strong>{esc(e["date_display"])}</strong>{domain}{sep} '
            f'{entry_title_html(e)}{rest}</li>')


def render_global_archive(archives):
    seen = set()
    deduped = []
    for idx, e in enumerate((e for a in archives for e in a["entries"])):
        key = (e["domain"], e["date_display"], e["title"], e["primary_url"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append((e["date_sort_key"], idx, e))

    dated = sorted((d for d in deduped if d[0]), key=lambda d: d[:2], reverse=True)
    undated = [d for d in deduped if not d[0]]
    items = "\n".join(entry_li(e, show_domain=True) for _, _, e in dated + undated)

    return f"""
  <section class="starlink-archive card">
    <h2>Global Archive Timeline</h2>
    <p class="muted">All archived items across the three domains, newest first.</p>
    <ul class="archive-timeline">
{items}
    </ul>
  </section>"""


def render_domain_archives(archives):
    sections = []
    for arc in archives:
        slug = arc["domain"].lower()
        items = "\n".join(entry_li(e) for e in arc["entries"])
        sections.append(f"""
  <section class="starlink-domain-archive card">
    <h2>{esc(arc["domain"])} — Archive</h2>
    <p class="muted">{esc(arc["description"])}</p>
    <ul class="archive-list archive-list-{slug}">
{items}
    </ul>
  </section>""")
    return "\n".join(sections)


def render_timeline(incidents):
    items = "\n".join(
        f'      <li><strong>{esc(i.get("date", ""))}</strong> — {esc(i.get("summary", ""))}</li>'
        for i in sorted(incidents, key=lambda i: i.get("date", ""), reverse=True)
    )
    return f"""
  <section class="card">
    <h2>Incident Timeline</h2>
    <ul class="digest-timeline">
{items}
    </ul>
    <p class="digest-note">Quiet days are logged to keep an auditable record of checks.</p>
  </section>"""


def render_digest_section(digest):
    if not digest:
        return ""
    cards = []
    for name, summary, flag in digest["sections"]:
        badge = ('<span class="badge badge-yes">Updated</span>' if flag == "Yes"
                 else '<span class="badge badge-no">No change</span>')
        paras = [p.strip() for p in summary.split("\n\n") if p.strip()] or [summary]
        body = "".join(f"<p>{esc(p)}</p>" for p in paras)
        slug = name[:3].lower()
        cards.append(f"""
      <article class="digest-card digest-card-{slug}">
        <div class="digest-card-head"><h4>{esc(name)}</h4>{badge}</div>
        {body}
      </article>""")

    return f"""
  <section class="starlink-digest card">
    <div class="digest-header">
      <h2>Latest Digest</h2>
      <span class="digest-date muted">{esc(digest["date"])}</span>
    </div>
    <div class="digest-key-findings">{"".join(cards)}
    </div>
  </section>"""


def render_tiles(met, src_gp, src_decayed, deltas):
    if not met:
        return ""

    def delta_html(key):
        d = deltas.get(key)
        if d is None or d == 0:
            return ""
        return f'<div class="delta">{"▲" if d > 0 else "▼"} {d:+,.0f} · 30d</div>'

    tiles = [
        ("active", f"{met.get('active_count', 0):,}", "Active satellites",
         src_gp, "Source: CelesTrak Starlink GP/CSV", delta_html("active_count")),
        ("decayed", f"{met.get('decayed_total', 0):,}", "Total decayed",
         src_decayed, "Source: CelesTrak SATCAT recently decayed", ""),
        ("mass", f"{met.get('on_orbit_mass_kg', 0):,.0f}", "On-orbit mass (kg)",
         src_gp, "Derived from CelesTrak active counts × generation mass mix",
         delta_html("on_orbit_mass_kg")),
        ("reentry", f"{met.get('reentered_mass_kg', 0):,.0f}", "Re-entered mass (kg)",
         src_decayed, "Accumulated Starlink decays × generation mass mix",
         delta_html("reentered_mass_kg")),
        ("alumina", f"{met.get('alumina_kg', 0):,.0f}", "Al₂O₃ estimate (kg)",
         "#", "Al fraction × 1.89 kg Al₂O₃ per kg Al (upper-bound stoichiometry)",
         delta_html("alumina_kg")),
    ]
    out = []
    for slug, value, label, url, tip, delta in tiles:
        out.append(f"""
      <div class="tile tile-{slug}">
        <div class="k">{value}</div>
        <div class="t">{label}
          <a class="info" href="{esc(url)}" target="_blank" title="{esc(tip)}">ⓘ</a>
        </div>{delta}
      </div>""")
    return f'<div class="tiles">{"".join(out)}</div>'


def render_chart_cards(series_by_key, sources):
    cards = []
    for spec in CHART_SPECS:
        series = series_by_key[spec["key"]]
        unit_head = esc(spec["unit"] or "Value")
        rows = "".join(
            f'<tr><td>{esc(p["date"])}</td><td>{p["value"]:,.0f}</td></tr>'
            for p in reversed(series)
        )
        cards.append(f"""
      <div class="card chart-card">
        <h3><span class="step">Step {spec["step"]}</span> {esc(spec["title"])}
          <a class="info" href="{esc(sources[spec["source"]])}" target="_blank"
             title="{esc(spec["info_tip"])}">ⓘ</a>
        </h3>
        <div class="chart-legend">
          <span class="key"><span class="key-line" style="background:{spec["color"]}"></span>Observed</span>
          <span class="key"><span class="key-line key-dash" style="border-color:{spec["color"]}"></span>Projected (linear)</span>
        </div>
        <figure class="chart" data-key="{spec["key"]}">
          <div class="chart-plot"><div class="chart-tooltip" role="status"></div></div>
        </figure>
        <p class="chart-caption">{esc(spec["caption"])}</p>
        <details class="chart-table">
          <summary>Data table</summary>
          <table><thead><tr><th>Date</th><th>{unit_head}</th></tr></thead><tbody>{rows}</tbody></table>
        </details>
      </div>""")
    return "\n".join(cards)


def render_sources(sources):
    items = []
    for s in sources:
        label = esc(s.get("label", ""))
        if s.get("url"):
            label = (f'<a href="{esc(s["url"])}" target="_blank" '
                     f'rel="noopener noreferrer">{label}</a>')
        items.append(f'      <li><strong>{label}</strong> — {esc(s.get("description", ""))}</li>')
    return "\n".join(items)


CSS = """
  :root {
    --bg:#0b1220; --fg:#e6edf3; --muted:#9fb0bd;
    --card:#0f172a; --card2:#0d1528; --ring:#1f2937;
    --accent:#60a5fa;
    --env:#34d399; --cyb:#f97316; --ast:#a78bfa;
  }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--bg); color:var(--fg); font:16px/1.6 ui-sans-serif,system-ui,'Segoe UI',Roboto,sans-serif; }
  a { color:var(--accent); text-decoration:none; } a:hover { text-decoration:underline; }
  h1,h2,h3,h4 { line-height:1.25; }
  h2 { font-size:1.25rem; margin-bottom:12px; }
  h3 { font-size:1.05rem; margin-bottom:10px; }
  h4 { font-size:.95rem; margin-bottom:6px; }
  p { margin-bottom:.75rem; }
  ul { margin:.5rem 0 .75rem 1.4rem; }
  li { margin-bottom:.3rem; }
  code { font-size:.85em; background:#12203a; padding:2px 6px; border-radius:4px; }

  header { padding:20px 16px; border-bottom:1px solid var(--ring); }
  footer { padding:16px; border-top:1px solid var(--ring); color:var(--muted); font-size:.88rem; text-align:center; }
  .wrap { max-width:1160px; margin:0 auto; padding:0 16px; }
  .muted { color:var(--muted); font-size:.9rem; }
  section { margin-bottom:24px; }

  .card {
    background:var(--card); border-radius:14px; padding:20px 22px;
    box-shadow:0 4px 20px #00000060, inset 0 1px 0 #ffffff0d;
    border:1px solid var(--ring);
  }
  .grid { display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(340px,1fr)); }
  .grid-charts { grid-template-columns:repeat(auto-fit,minmax(420px,1fr)); }

  /* metric tiles */
  .tiles { display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); margin:16px 0 0; }
  .tile { background:var(--card2); border:1px solid #1a2c47; border-radius:12px; padding:14px 16px; }
  .tile .k { font-size:26px; font-weight:700; letter-spacing:-.5px; }
  .tile .t { color:var(--muted); font-size:.8rem; margin-top:2px; }
  .tile .delta { color:var(--muted); font-size:.75rem; margin-top:4px; }
  .tile-active .k { color:#60a5fa; }
  .tile-decayed .k { color:#f87171; }
  .tile-mass .k { color:#34d399; }
  .tile-reentry .k { color:#f97316; }
  .tile-alumina .k { color:#a78bfa; }
  a.info { font-weight:700; margin-left:5px; color:var(--muted); font-size:.8em;
           border-bottom:1px dotted currentColor; cursor:help; text-decoration:none; }
  a.info:hover { color:var(--accent); }

  /* chart controls */
  .controls { display:flex; gap:20px; flex-wrap:wrap; align-items:center; margin:4px 0 16px; }
  .control-group { display:flex; gap:6px; align-items:center; color:var(--muted); font-size:.82rem; }
  .control-group button {
    background:var(--card2); color:var(--muted); border:1px solid var(--ring);
    padding:3px 10px; border-radius:8px; cursor:pointer; font:inherit; font-size:.8rem;
  }
  .control-group button:hover { color:var(--fg); }
  .control-group button[aria-pressed="true"] { color:var(--fg); border-color:var(--accent); background:#12203a; }

  /* chart cards */
  .chart-card { padding:14px 16px; }
  .chart-legend { display:flex; gap:16px; font-size:.78rem; color:var(--muted); margin-bottom:6px; }
  .key { display:inline-flex; align-items:center; gap:6px; }
  .key-line { display:inline-block; width:18px; height:2px; }
  .key-dash { height:0; border-top:2px dashed; background:none; }
  .chart { margin:0; }
  .chart-plot { position:relative; }
  .chart-plot svg { display:block; width:100%; }
  .chart-plot svg:focus { outline:1px solid var(--accent); outline-offset:2px; }
  .chart-tooltip {
    position:absolute; display:none; pointer-events:none; z-index:2;
    background:#0b1220f2; border:1px solid var(--ring); border-radius:8px;
    padding:6px 10px; font-size:.78rem; color:var(--muted); white-space:nowrap;
  }
  .chart-tooltip .val { font-weight:700; font-size:.92rem; color:var(--fg); }
  .chart-caption { color:var(--muted); font-size:.85rem; margin:10px 0 0; }
  .chart-table { margin-top:10px; font-size:.8rem; }
  .chart-table summary { cursor:pointer; color:var(--muted); }
  .chart-table table { border-collapse:collapse; margin-top:8px; width:100%; max-height:none; }
  .chart-table tbody { display:block; max-height:220px; overflow-y:auto; }
  .chart-table thead, .chart-table tbody tr { display:table; width:100%; table-layout:fixed; }
  .chart-table th, .chart-table td {
    text-align:left; padding:3px 8px; border-bottom:1px solid var(--ring);
    font-variant-numeric:tabular-nums;
  }
  .step { display:inline-block; background:#12203a; color:var(--accent); font-size:.7rem;
          font-weight:700; letter-spacing:.6px; text-transform:uppercase;
          padding:2px 8px; border-radius:10px; margin-right:8px; vertical-align:middle; }

  /* digest section */
  .digest-header { display:flex; align-items:baseline; gap:12px; margin-bottom:16px; }
  .digest-key-findings { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }
  .digest-card { border-radius:10px; padding:14px 16px; border:1px solid var(--ring); background:var(--card2); }
  .digest-card-env { border-left:3px solid var(--env); }
  .digest-card-cyb { border-left:3px solid var(--cyb); }
  .digest-card-ast { border-left:3px solid var(--ast); }
  .digest-card-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
  .badge { font-size:.72rem; font-weight:600; padding:2px 8px; border-radius:20px; letter-spacing:.4px; text-transform:uppercase; }
  .badge-yes { background:#134e2a; color:#4ade80; border:1px solid #166534; }
  .badge-no  { background:#1c1f2e; color:#6b7280; border:1px solid var(--ring); }

  /* timeline / archive */
  .digest-timeline { list-style:disc; padding-left:1.4rem; }
  .digest-note { font-size:.85rem; color:var(--muted); margin-top:8px; }
  .archive-timeline, .starlink-domain-archive ul { list-style:none; padding-left:0; margin-left:0; }
  .archive-timeline li, .starlink-domain-archive li {
    padding:5px 0; border-bottom:1px solid var(--ring); font-size:.9rem;
  }
  .archive-timeline li:last-child, .starlink-domain-archive li:last-child { border-bottom:none; }
  .archive-domain { font-size:.75rem; font-weight:600; padding:1px 7px; border-radius:10px; margin:0 4px; text-transform:uppercase; letter-spacing:.4px; }
  .archive-domain-environmental { background:#0d2e1e; color:var(--env); }
  .archive-domain-cybersecurity { background:#2d1a0a; color:var(--cyb); }
  .archive-domain-astronomical { background:#1e1640; color:var(--ast); }
  .archive-list-environmental li { border-left:3px solid var(--env); padding-left:10px; }
  .archive-list-cybersecurity li { border-left:3px solid var(--cyb); padding-left:10px; }
  .archive-list-astronomical  li { border-left:3px solid var(--ast); padding-left:10px; }
"""

# Client-side chart renderer: line + area wash for observed data, dashed linear
# projection, crosshair tooltip, keyboard stepping, shared range/horizon controls.
SCRIPT = """
(function () {
  'use strict';
  var DATA = JSON.parse(document.getElementById('sw-data').textContent);
  var DAY = 86400000;
  var NS = 'http://www.w3.org/2000/svg';
  var GRID = '#1f2937', INK = '#e6edf3', MUTED = '#9fb0bd';
  var state = { range: 0, horizon: 180 };

  function fmtCompact(v) {
    var a = Math.abs(v);
    if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 2) + 'M';
    if (a >= 1e3) return (v / 1e3).toFixed(a >= 1e4 ? 0 : 1) + 'K';
    return String(Math.round(v));
  }
  function fmtFull(v) { return Math.round(v).toLocaleString('en-US'); }
  function fmtDate(t, withYear) {
    var opts = { month: 'short', day: 'numeric', timeZone: 'UTC' };
    if (withYear) opts.year = 'numeric';
    return new Date(t).toLocaleDateString('en-US', opts);
  }
  function parseDate(iso) { return Date.parse(iso + 'T00:00:00Z'); }

  function trendSlope(pts) {
    // least-squares slope in value/day, or null if the fit is degenerate
    var n = pts.length;
    if (n < 2) return null;
    var t0 = pts[0].t, sx = 0, sy = 0, sxx = 0, sxy = 0;
    pts.forEach(function (p) {
      var x = (p.t - t0) / DAY;
      sx += x; sy += p.v; sxx += x * x; sxy += x * p.v;
    });
    var d = n * sxx - sx * sx;
    return d ? (n * sxy - sx * sy) / d : null;
  }

  function niceStep(span, target) {
    var raw = span / target;
    var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var norm = raw / mag;
    return (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  }

  function el(name, attrs, parent) {
    var node = document.createElementNS(NS, name);
    for (var k in attrs) node.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(node);
    return node;
  }

  function buildChart(fig) {
    var key = fig.getAttribute('data-key');
    var spec = DATA.charts[key];
    var observed = DATA.series[key].map(function (p) {
      return { t: parseDate(p.date), v: p.value };
    });
    var holder = fig.querySelector('.chart-plot');
    var tooltip = fig.querySelector('.chart-tooltip');
    var hover = null; // { samples, x, y, cross, dot, svg, plotW }
    var hoverIdx = -1;

    function showPoint(i) {
      if (!hover || !hover.samples.length) return;
      hoverIdx = Math.max(0, Math.min(hover.samples.length - 1, i));
      var s = hover.samples[hoverIdx];
      var px = hover.x(s.t), py = hover.y(s.v);
      hover.cross.setAttribute('x1', px);
      hover.cross.setAttribute('x2', px);
      hover.cross.style.display = '';
      hover.dot.setAttribute('cx', px);
      hover.dot.setAttribute('cy', py);
      hover.dot.style.display = '';

      tooltip.textContent = '';
      var val = document.createElement('div');
      val.className = 'val';
      val.textContent = fmtFull(s.v) + (spec.unit ? ' ' + spec.unit : '');
      var date = document.createElement('div');
      date.textContent = fmtDate(s.t, true) + (s.proj ? ' · projected' : '');
      tooltip.appendChild(val);
      tooltip.appendChild(date);
      tooltip.style.display = 'block';
      var tw = tooltip.offsetWidth;
      var scale = holder.clientWidth / hover.w;
      var left = px * scale + 12;
      if (left + tw > holder.clientWidth - 4) left = px * scale - tw - 12;
      tooltip.style.left = Math.max(4, left) + 'px';
      tooltip.style.top = Math.max(0, py * scale - 34) + 'px';
    }

    function hidePoint() {
      if (!hover) return;
      hover.cross.style.display = 'none';
      hover.dot.style.display = 'none';
      tooltip.style.display = 'none';
      hoverIdx = -1;
    }

    function render() {
      holder.querySelectorAll('svg').forEach(function (n) { n.remove(); });
      hidePoint();
      if (!observed.length) {
        holder.textContent = 'No data yet';
        return;
      }
      var W = Math.max(holder.clientWidth, 320), H = 240;
      var M = { l: 48, r: 64, t: 14, b: 26 };
      var lastObs = observed[observed.length - 1];

      var visible = observed;
      if (state.range > 0) {
        var cut = lastObs.t - state.range * DAY;
        visible = observed.filter(function (p) { return p.t >= cut; });
      }

      // Project the fitted slope forward from the last observed value; a
      // cumulative series can only grow, so its slope is clamped at zero.
      var slope = trendSlope(observed);
      if (slope !== null && spec.cumulative) slope = Math.max(0, slope);
      var projected = [];
      if (slope !== null && state.horizon > 0) {
        var proj = function (t) {
          return Math.max(0, lastObs.v + slope * (t - lastObs.t) / DAY);
        };
        for (var t = lastObs.t + 7 * DAY; t < lastObs.t + state.horizon * DAY; t += 7 * DAY) {
          projected.push({ t: t, v: proj(t), proj: true });
        }
        var end = lastObs.t + state.horizon * DAY;
        projected.push({ t: end, v: proj(end), proj: true });
      }

      var all = visible.concat(projected);
      var t0 = visible[0].t, t1 = all[all.length - 1].t;
      var vMin = Infinity, vMax = -Infinity;
      all.forEach(function (p) {
        if (p.v < vMin) vMin = p.v;
        if (p.v > vMax) vMax = p.v;
      });
      if (vMin === vMax) { vMin -= 1; vMax += 1; }
      var pad = (vMax - vMin) * 0.08;
      vMin = Math.max(0, vMin - pad); vMax += pad;

      var plotW = W - M.l - M.r, plotH = H - M.t - M.b;
      function x(t) { return M.l + (t - t0) / (t1 - t0 || 1) * plotW; }
      function y(v) { return M.t + (1 - (v - vMin) / (vMax - vMin)) * plotH; }

      var svg = el('svg', {
        viewBox: '0 0 ' + W + ' ' + H, role: 'img', tabindex: 0,
        'aria-label': spec.title + ' — interactive chart; use arrow keys to step through values'
      });

      // y grid + labels
      var yStep = niceStep(vMax - vMin, 4);
      for (var v = Math.ceil(vMin / yStep) * yStep; v <= vMax; v += yStep) {
        el('line', { x1: M.l, x2: W - M.r, y1: y(v), y2: y(v), stroke: GRID, 'stroke-width': 1 }, svg);
        el('text', {
          x: M.l - 8, y: y(v) + 4, fill: MUTED, 'font-size': 11, 'text-anchor': 'end'
        }, svg).textContent = fmtCompact(v);
      }

      // x labels
      var nx = W < 480 ? 3 : 5;
      var firstYear = new Date(t0).getUTCFullYear();
      for (var i = 0; i < nx; i++) {
        var tt = t0 + (t1 - t0) * i / (nx - 1);
        var anchor = i === 0 ? 'start' : i === nx - 1 ? 'end' : 'middle';
        el('text', {
          x: x(tt), y: H - 8, fill: MUTED, 'font-size': 11, 'text-anchor': anchor
        }, svg).textContent = fmtDate(tt, new Date(tt).getUTCFullYear() !== firstYear);
      }

      // observed area wash + line
      var lineD = visible.map(function (p, i) {
        return (i ? 'L' : 'M') + x(p.t).toFixed(1) + ' ' + y(p.v).toFixed(1);
      }).join('');
      var baseY = (M.t + plotH).toFixed(1);
      el('path', {
        d: lineD + 'L' + x(lastObs.t).toFixed(1) + ' ' + baseY +
           'L' + x(visible[0].t).toFixed(1) + ' ' + baseY + 'Z',
        fill: spec.color, opacity: 0.1
      }, svg);
      el('path', {
        d: lineD, fill: 'none', stroke: spec.color, 'stroke-width': 2,
        'stroke-linecap': 'round', 'stroke-linejoin': 'round'
      }, svg);

      // projection: dashed line from last observed point, labeled endpoint
      var endPt = lastObs;
      if (projected.length) {
        var projD = [{ t: lastObs.t, v: lastObs.v }].concat(projected).map(function (p, i) {
          return (i ? 'L' : 'M') + x(p.t).toFixed(1) + ' ' + y(p.v).toFixed(1);
        }).join('');
        el('path', {
          d: projD, fill: 'none', stroke: spec.color, 'stroke-width': 2,
          'stroke-dasharray': '6 5', 'stroke-linecap': 'round'
        }, svg);
        endPt = projected[projected.length - 1];
      }
      el('circle', {
        cx: x(endPt.t), cy: y(endPt.v), r: 4.5,
        fill: spec.color, stroke: '#0f172a', 'stroke-width': 2
      }, svg);
      el('text', {
        x: Math.min(x(endPt.t) + 8, W - 2), y: y(endPt.v) + 4,
        fill: INK, 'font-size': 11, 'font-weight': 600, 'text-anchor': 'start'
      }, svg).textContent = fmtCompact(endPt.v);

      // hover layer
      var cross = el('line', {
        y1: M.t, y2: M.t + plotH, stroke: MUTED, 'stroke-width': 1, style: 'display:none'
      }, svg);
      var dot = el('circle', {
        r: 4.5, fill: spec.color, stroke: '#0f172a', 'stroke-width': 2, style: 'display:none'
      }, svg);
      hover = { samples: all, x: x, y: y, cross: cross, dot: dot, w: W };

      svg.addEventListener('pointermove', function (ev) {
        var rect = svg.getBoundingClientRect();
        var mx = (ev.clientX - rect.left) / rect.width * W;
        var best = 0, bestD = Infinity;
        all.forEach(function (p, i) {
          var d = Math.abs(x(p.t) - mx);
          if (d < bestD) { bestD = d; best = i; }
        });
        showPoint(best);
      });
      svg.addEventListener('pointerleave', hidePoint);
      svg.addEventListener('blur', hidePoint);
      svg.addEventListener('keydown', function (ev) {
        if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight') {
          ev.preventDefault();
          var base = hoverIdx < 0 ? all.length - 1 : hoverIdx;
          showPoint(base + (ev.key === 'ArrowRight' ? 1 : -1));
        } else if (ev.key === 'Escape') {
          hidePoint();
        }
      });

      holder.appendChild(svg);
    }

    return render;
  }

  var charts = [];
  document.querySelectorAll('.chart[data-key]').forEach(function (fig) {
    charts.push(buildChart(fig));
  });
  function renderAll() { charts.forEach(function (r) { r(); }); }

  document.querySelectorAll('.control-group').forEach(function (group) {
    var prop = group.getAttribute('data-control');
    group.querySelectorAll('button').forEach(function (btn) {
      btn.addEventListener('click', function () {
        state[prop] = Number(btn.getAttribute('data-value'));
        group.querySelectorAll('button').forEach(function (b) {
          b.setAttribute('aria-pressed', b === btn ? 'true' : 'false');
        });
        renderAll();
      });
    });
  });

  var resizeTimer = null;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(renderAll, 150);
  });

  renderAll();
})();
"""


# ---------- build ----------
def build():
    met = load_json(DATA / "metrics.json", {})
    src = met.get("sources", {})
    sources_urls = {
        "gp": src.get("celestrak_gp_csv", "https://celestrak.org/NORAD/elements/"),
        "decayed": src.get("celestrak_decayed", "https://celestrak.org/satcat/decayed-with-last.php"),
    }

    incidents = load_json(DATA / "incidents.json", [])
    sources = load_json(DATA / "sources.json", [])
    archives = load_archives()
    digest = load_latest_digest()

    series_by_key = {spec["key"]: load_series(spec["key"]) for spec in CHART_SPECS}
    deltas = {key: delta_30d(series) for key, series in series_by_key.items()}

    chart_data = {
        "series": series_by_key,
        "charts": {
            spec["key"]: {
                "title": spec["title"], "color": spec["color"], "unit": spec["unit"],
                "cumulative": spec.get("cumulative", False),
            }
            for spec in CHART_SPECS
        },
    }
    chart_json = json.dumps(chart_data, separators=(",", ":")).replace("</", "<\\/")

    built = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Starlink Watch — Metrics &amp; Digest</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="wrap" style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
    <div>
      <h1 style="font-size:1.4rem">Starlink Watch</h1>
      <div class="muted">Environmental · Cybersecurity · Astronomical</div>
    </div>
    <div class="muted" style="margin-left:auto;font-size:.82rem">Built {esc(built)}</div>
  </div>
</header>

<main class="wrap" style="padding:24px 0 48px">

  <section class="card">
    <h2>Constellation Metrics</h2>
    <p>
      Every satellite launched today is a re-entry event roughly five years from now, and every
      re-entry leaves alumina in the upper atmosphere. These tiles are the current state of that
      chain; the charts below trace it step by step.
    </p>
    {render_tiles(met, sources_urls["gp"], sources_urls["decayed"], deltas)}
  </section>

  <section class="card">
    <h2>From Launch to the Ozone Layer</h2>
    <p>
      Starlink satellites operate for about five years, then deorbit and burn up. Re-entry
      converts much of each satellite&rsquo;s aluminum into Al₂O₃ (&ldquo;alumina&rdquo;)
      nanoparticles at 50&ndash;85&nbsp;km altitude, which settle into the stratosphere —
      the ozone layer — over years to decades.
    </p>

    <div class="controls">
      <div class="control-group" data-control="range">
        <span>Range</span>
        <button type="button" data-value="30" aria-pressed="false">30d</button>
        <button type="button" data-value="90" aria-pressed="false">90d</button>
        <button type="button" data-value="0" aria-pressed="true">All</button>
      </div>
      <div class="control-group" data-control="horizon">
        <span>Projection</span>
        <button type="button" data-value="0" aria-pressed="false">Off</button>
        <button type="button" data-value="90" aria-pressed="false">+90d</button>
        <button type="button" data-value="180" aria-pressed="true">+180d</button>
        <button type="button" data-value="365" aria-pressed="false">+1y</button>
      </div>
      <span class="muted" style="font-size:.78rem">Projections are linear fits to the observed series.</span>
    </div>
    <noscript><p class="muted">Interactive charts need JavaScript — the data tables under each chart carry the same values.</p></noscript>

    <div class="grid grid-charts">
{render_chart_cards(series_by_key, sources_urls)}
    </div>

    <h3 style="margin-top:18px">What the research says</h3>
    <ul>
      <li>
        <a href="https://www.pnas.org/doi/10.1073/pnas.2313374120" target="_blank" rel="noopener noreferrer">Murphy et&nbsp;al. 2023 (PNAS)</a>
        — ~10% of stratospheric aerosol particles already contain aluminum and other metals from
        spacecraft re-entries; expected to reach ~50% as planned constellations build out.
      </li>
      <li>
        <a href="https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2024GL109280" target="_blank" rel="noopener noreferrer">Ferreira et&nbsp;al. 2024 (GRL)</a>
        — a ~250&nbsp;kg satellite yields roughly 30&nbsp;kg of Al₂O₃ nanoparticles; a full
        megaconstellation era could inject 360+&nbsp;tonnes per year, several times the natural
        meteoric background.
      </li>
      <li>
        <strong>Delayed, not avoided</strong> — particles take years to decades to settle to
        ozone-layer altitudes, where alumina surfaces catalyze the chlorine activation that
        drives catalytic ozone loss.
      </li>
      <li>
        <strong>Starlink dominates the flux</strong> — the largest constellation in low Earth
        orbit, on a five-year replacement cycle, so its re-entry rate tracks its launch rate.
      </li>
    </ul>
    <p class="muted">
      The alumina series is a transparent upper-bound estimate, not a measurement. All
      assumptions are tunable in <code>data/starlink_config.yml</code>.
    </p>
  </section>

  {render_digest_section(digest)}

  {render_timeline(incidents)}

  <section class="card">
    <h2>Methodology</h2>
    <ul>
      <li><strong style="color:var(--env)">Environmental</strong> — re-entries, alumina production, debris, and climate/ozone findings.</li>
      <li><strong style="color:var(--cyb)">Cybersecurity</strong> — vulnerabilities and incidents involving terminals, ground infrastructure, or Starlink-dependent networks.</li>
      <li><strong style="color:var(--ast)">Astronomical</strong> — optical streaks, survey contamination, radio interference, and observatory mitigations.</li>
    </ul>
    <p>
      Object tracking uses CelesTrak Starlink GP/CSV (active) and SATCAT decay records
      (re-entries). Mass and alumina estimates apply the generation mass mix and stoichiometric
      Al→Al₂O₃ conversion defined in <code>data/starlink_config.yml</code>. News monitoring is a
      deterministic keyword filter over the RSS feeds in <code>scripts/feeds.yml</code> — no LLM,
      no external API.
    </p>
    <h3>Data Sources</h3>
    <ul>
{render_sources(sources)}
    </ul>
  </section>

{render_global_archive(archives)}

{render_domain_archives(archives)}

</main>

<footer><div class="wrap muted">
  Starlink-only; prioritizes criticisms, risks, and concrete events. Charts update on each run.
</div></footer>

<script id="sw-data" type="application/json">{chart_json}</script>
<script>{SCRIPT}</script>
</body></html>"""

    SITE.mkdir(exist_ok=True, parents=True)
    (SITE / "index.html").write_text(page, encoding="utf-8")
    print(f"Site built: {SITE / 'index.html'}")


if __name__ == "__main__":
    build()
