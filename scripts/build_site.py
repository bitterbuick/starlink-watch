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
        return json.loads(p.read_text(encoding="utf-8"))

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
        domain_slug = domain.lower()
        items.append(
            f"      <li>\n        <strong>{date_disp}</strong> — <span class=\"archive-domain archive-domain-{domain_slug}\">{domain}</span> — {title_html}{rest_html}\n      </li>"
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
        f"{indent}<li>\n{nested}<strong>Most recent confirmed Starlink re-entry</strong> — The latest Starlink re-entry record in the CelesTrak/SATCAT &ldquo;decayed objects&rdquo; dataset remains unchanged relative to the prior digest unless otherwise noted above.\n{indent}</li>"
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

def chart(df, title, out_png, color="#60a5fa"):
    BG = "#0b1220"
    CARD = "#0d1528"
    GRID = "#1f2937"
    FG = "#e6edf3"
    MUTED = "#9fb0bd"

    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(CARD)

    if df.empty:
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center",
                color=MUTED, fontsize=14, transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
    else:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        ax.plot(df["date"], df["value"], color=color, linewidth=2.0, zorder=3)
        ax.fill_between(df["date"], df["value"], alpha=0.12, color=color, zorder=2)
        ax.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, _: f"{x:,.0f}")
        )
        ax.tick_params(colors=MUTED, labelsize=10)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID)
        ax.grid(True, color=GRID, linewidth=0.7, zorder=1)
        ax.set_xlabel("")

    ax.set_title(title, color=FG, fontsize=12, pad=10)
    fig.tight_layout(pad=1.5)
    fig.savefig(out_png, dpi=160, facecolor=BG)
    plt.close(fig)

def load_latest_digest():
    """Return parsed fields from the most recent event file, or None."""
    if not EVENTS.exists():
        return None
    files = sorted(EVENTS.glob("*.md"), reverse=True)
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

    digest_date = re.search(r"## Starlink Daily Digest — (\S+)", text)
    digest_date = digest_date.group(1) if digest_date else latest.stem[:10]

    return {
        "date": digest_date,
        "fname": latest.name,
        "environmental_summary": section("Environmental"),
        "cybersecurity_summary": section("Cybersecurity"),
        "astronomical_summary": section("Astronomical"),
        "environmental_update": update_flag("Environmental"),
        "cybersecurity_update": update_flag("Cybersecurity"),
        "astronomical_update": update_flag("Astronomical"),
    }


def render_digest_section(digest):
    if not digest:
        return ""

    def badge(flag):
        if flag == "Yes":
            return '<span class="badge badge-yes">Updated</span>'
        return '<span class="badge badge-no">No change</span>'

    def esc_nl(s):
        paras = [p.strip() for p in s.split("\n\n") if p.strip()]
        return "".join(f"<p>{html.escape(p)}</p>" for p in paras) if paras else f"<p>{html.escape(s)}</p>"

    env_badge = badge(digest["environmental_update"])
    cyb_badge = badge(digest["cybersecurity_update"])
    ast_badge = badge(digest["astronomical_update"])

    return f"""
  <section class="starlink-digest card" style="margin-top:24px">
    <div class="digest-header">
      <h2>Latest Digest</h2>
      <span class="digest-date muted">{html.escape(digest['date'])}</span>
    </div>

    <div class="digest-key-findings">

      <article class="digest-card digest-card-env">
        <div class="digest-card-head">
          <h4>Environmental</h4>
          {env_badge}
        </div>
        {esc_nl(digest['environmental_summary'])}
      </article>

      <article class="digest-card digest-card-cyb">
        <div class="digest-card-head">
          <h4>Cybersecurity</h4>
          {cyb_badge}
        </div>
        {esc_nl(digest['cybersecurity_summary'])}
      </article>

      <article class="digest-card digest-card-ast">
        <div class="digest-card-head">
          <h4>Astronomical</h4>
          {ast_badge}
        </div>
        {esc_nl(digest['astronomical_summary'])}
      </article>

    </div>
  </section>"""


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
    chart(load_series("active_count"),      "Active Starlink satellites (count)", ASSETS/"active.png",  color="#60a5fa")
    chart(load_series("on_orbit_mass_kg"),  "Estimated on-orbit mass (kg)",       ASSETS/"onorbit.png", color="#34d399")
    chart(load_series("reentered_mass_kg"), "Estimated re-entered mass (kg)",     ASSETS/"reentry.png", color="#f97316")
    chart(load_series("alumina_kg"),        "Estimated Al₂O₃ formed (kg)",        ASSETS/"alumina.png", color="#a78bfa")

    digest = load_latest_digest()
    digest_section_html = render_digest_section(digest)

    built = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # tiles with inline citations (ⓘ)
    tiles = ""
    if met:
        tiles = f"""
        <div class="tiles">
          <div class="tile tile-active">
            <div class="k">{met.get('active_count',0):,}</div>
            <div class="t">Active satellites
              <a class="info" href="{html.escape(src_gp)}" target="_blank" title="Source: CelesTrak Starlink GP/CSV">ⓘ</a>
            </div>
          </div>
          <div class="tile tile-decayed">
            <div class="k">{met.get('decayed_total',0):,}</div>
            <div class="t">Total decayed
              <a class="info" href="{html.escape(src_decayed)}" target="_blank" title="Source: CelesTrak SATCAT recently decayed">ⓘ</a>
            </div>
          </div>
          <div class="tile tile-mass">
            <div class="k">{met.get('on_orbit_mass_kg',0):,.0f}</div>
            <div class="t">On-orbit mass (kg)
              <a class="info" href="{html.escape(src_gp)}" target="_blank" title="Derived from CelesTrak active counts × generation mass mix">ⓘ</a>
            </div>
          </div>
          <div class="tile tile-reentry">
            <div class="k">{met.get('reentered_mass_kg',0):,.0f}</div>
            <div class="t">Re-entered mass (kg)
              <a class="info" href="{html.escape(src_decayed)}" target="_blank" title="Accumulated Starlink decays × generation mass mix">ⓘ</a>
            </div>
          </div>
          <div class="tile tile-alumina">
            <div class="k">{met.get('alumina_kg',0):,.0f}</div>
            <div class="t">Al₂O₃ estimate (kg)
              <a class="info" href="#" title="Al fraction × 1.89 kg Al₂O₃ per kg Al (upper-bound stoichiometry)">ⓘ</a>
            </div>
          </div>
        </div>
        """

    # page HTML
    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Starlink Watch — Metrics &amp; Digest</title>
<style>
  :root {{
    --bg:#0b1220; --fg:#e6edf3; --muted:#9fb0bd;
    --card:#0f172a; --card2:#0d1528; --ring:#1f2937;
    --accent:#60a5fa;
    --env:#34d399; --cyb:#f97316; --ast:#a78bfa;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--fg); font:16px/1.6 ui-sans-serif,system-ui,’Segoe UI’,Roboto,sans-serif; }}
  a {{ color:var(--accent); text-decoration:none; }} a:hover {{ text-decoration:underline; }}
  h1,h2,h3,h4 {{ line-height:1.25; }}
  h2 {{ font-size:1.25rem; margin-bottom:14px; }}
  h3 {{ font-size:1.05rem; margin-bottom:10px; }}
  h4 {{ font-size:.95rem; margin-bottom:6px; }}
  p {{ margin-bottom:.75rem; }}
  ul {{ margin:.5rem 0 .75rem 1.4rem; }}
  li {{ margin-bottom:.3rem; }}
  code {{ font-size:.85em; background:#12203a; padding:2px 6px; border-radius:4px; }}
  hr {{ border:none; border-top:1px solid var(--ring); margin:20px 0; }}

  header {{ padding:20px 16px; border-bottom:1px solid var(--ring); }}
  footer {{ padding:16px; border-top:1px solid var(--ring); color:var(--muted); font-size:.88rem; text-align:center; }}
  .wrap {{ max-width:1160px; margin:0 auto; padding:0 16px; }}
  .muted {{ color:var(--muted); font-size:.9rem; }}

  .card {{
    background:var(--card); border-radius:14px; padding:20px 22px;
    box-shadow:0 4px 20px #00000060, inset 0 1px 0 #ffffff0d;
    border:1px solid var(--ring);
  }}
  .grid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(340px,1fr)); }}

  /* metric tiles */
  .tiles {{ display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); margin:16px 0; }}
  .tile {{ background:var(--card2); border:1px solid #1a2c47; border-radius:12px; padding:14px 16px; }}
  .tile .k {{ font-size:26px; font-weight:700; letter-spacing:-.5px; }}
  .tile .t {{ color:var(--muted); font-size:.8rem; margin-top:2px; }}
  .tile-active .k {{ color:#60a5fa; }}
  .tile-decayed .k {{ color:#f87171; }}
  .tile-mass .k {{ color:#34d399; }}
  .tile-reentry .k {{ color:#f97316; }}
  .tile-alumina .k {{ color:#a78bfa; }}
  a.info {{ font-weight:700; margin-left:5px; color:var(--muted); font-size:.8em;
            border-bottom:1px dotted currentColor; cursor:help; text-decoration:none; }}
  a.info:hover {{ color:var(--accent); }}

  /* chart cards */
  img.chart {{ width:100%; height:auto; border-radius:8px; display:block; }}

  /* digest section */
  .digest-header {{ display:flex; align-items:baseline; gap:12px; margin-bottom:16px; }}
  .digest-date {{ font-size:.85rem; color:var(--muted); }}
  .digest-key-findings {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; margin:16px 0; }}
  .digest-card {{ border-radius:10px; padding:14px 16px; border:1px solid var(--ring); background:var(--card2); }}
  .digest-card-env {{ border-left:3px solid var(--env); }}
  .digest-card-cyb {{ border-left:3px solid var(--cyb); }}
  .digest-card-ast {{ border-left:3px solid var(--ast); }}
  .digest-card-head {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }}
  .digest-card-head h4 {{ margin:0; }}
  .badge {{ font-size:.72rem; font-weight:600; padding:2px 8px; border-radius:20px; letter-spacing:.4px; text-transform:uppercase; }}
  .badge-yes {{ background:#134e2a; color:#4ade80; border:1px solid #166534; }}
  .badge-no  {{ background:#1c1f2e; color:#6b7280; border:1px solid var(--ring); }}

  /* timeline / archive */
  .digest-timeline {{ list-style:disc; padding-left:1.4rem; }}
  .digest-note {{ font-size:.85rem; color:var(--muted); margin-top:8px; }}
  .archive-timeline {{ list-style:none; padding-left:0; }}
  .archive-timeline li {{ padding:5px 0; border-bottom:1px solid var(--ring); font-size:.9rem; }}
  .archive-timeline li:last-child {{ border-bottom:none; }}
  .archive-domain {{ font-size:.75rem; font-weight:600; padding:1px 7px; border-radius:10px; margin:0 4px; text-transform:uppercase; letter-spacing:.4px; }}
  .archive-domain-environmental {{ background:#0d2e1e; color:var(--env); }}
  .archive-domain-cybersecurity {{ background:#2d1a0a; color:var(--cyb); }}
  .archive-domain-astronomical {{ background:#1e1640; color:var(--ast); }}
  .starlink-domain-archive ul {{ list-style:none; padding-left:0; }}
  .starlink-domain-archive li {{ padding:5px 0; border-bottom:1px solid var(--ring); font-size:.9rem; }}
  .starlink-domain-archive li:last-child {{ border-bottom:none; }}
  .archive-list-environmental li {{ border-left:3px solid var(--env); padding-left:10px; }}
  .archive-list-cybersecurity li {{ border-left:3px solid var(--cyb); padding-left:10px; }}
  .archive-list-astronomical  li {{ border-left:3px solid var(--ast); padding-left:10px; }}
  section {{ margin-bottom:24px; }}
</style>
</head>
<body>
<header>
  <div class="wrap" style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
    <div>
      <h1 style="font-size:1.4rem">Starlink Watch</h1>
      <div class="muted">Environmental · Cybersecurity · Astronomical</div>
    </div>
    <div class="muted" style="margin-left:auto;font-size:.82rem">Built {html.escape(datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))}</div>
  </div>
</header>

<main class="wrap" style="padding:24px 0 48px">

  <section class="card">
    <h2>Constellation Metrics</h2>
    {tiles}
    <div class="grid">
      <div class="card" style="padding:14px">
        <h3>Active satellites
          <a class="info" href="{html.escape(src_gp)}" target="_blank" title="CelesTrak Starlink group (GP/CSV)">ⓘ</a>
        </h3>
        <img class="chart" src="assets/active.png" alt="Active satellite count over time">
      </div>
      <div class="card" style="padding:14px">
        <h3>On-orbit mass (kg)
          <a class="info" href="{html.escape(src_gp)}" target="_blank" title="Derived from active counts × generation masses (configurable)">ⓘ</a>
        </h3>
        <img class="chart" src="assets/onorbit.png" alt="Estimated on-orbit mass">
      </div>
      <div class="card" style="padding:14px">
        <h3>Re-entered mass (kg)
          <a class="info" href="{html.escape(src_decayed)}" target="_blank" title="Accumulated Starlink decays (CelesTrak SATCAT) × generation masses">ⓘ</a>
        </h3>
        <img class="chart" src="assets/reentry.png" alt="Estimated re-entered mass">
      </div>
      <div class="card" style="padding:14px">
        <h3>Al₂O₃ estimate (kg)
          <a class="info" href="#" title="Al fraction × 1.89 kg Al₂O₃ per kg Al (upper-bound stoichiometry); tune in data/starlink_config.yml">ⓘ</a>
        </h3>
        <img class="chart" src="assets/alumina.png" alt="Estimated alumina formed">
      </div>
    </div>
    <p class="muted" style="margin-top:12px">
      Mass mix and assumptions editable in <code>data/starlink_config.yml</code>. Charts regenerate on each run.
    </p>
  </section>

  {digest_section_html}

  <section class="card">
    <h2>Incident Timeline</h2>
    <ul class="digest-timeline">
      {timeline_html}
    </ul>
    <p class="digest-note">
      Quiet days are logged explicitly to preserve an auditable history of checks.
    </p>
  </section>

  <section class="card">
    <h2>Methodology &amp; Rationale</h2>

    <h3>Why These Domains Are Tracked</h3>
    <p>Three classes of risk where a constellation the size of Starlink can generate outsized systemic effects:</p>
    <ul>
      <li><strong style="color:var(--env)">Environmental</strong> — Atmospheric re-entries, alumina production, debris generation, and regulatory or scientific findings relating to climate and ozone impacts.</li>
      <li><strong style="color:var(--cyb)">Cybersecurity</strong> — Vulnerabilities, exploitation, and operational security issues involving user terminals, ground infrastructure, or Starlink’s role in high-value networks.</li>
      <li><strong style="color:var(--ast)">Astronomical</strong> — Optical streaks, survey contamination, radio interference, and mitigation measures affecting professional observatories and large survey projects.</li>
    </ul>

    <h3>Environmental Modeling</h3>
    <ul>
      <li><strong>Object and decay tracking</strong> — CelesTrak Starlink GP/CSV (active elements) and SATCAT recently decayed (confirmed re-entries).</li>
      <li><strong>Alumina estimates</strong> — Generation mass mix defined in <code>data/starlink_config.yml</code>; aluminum fraction × 1.89 kg Al₂O₃ per kg Al (upper-bound stoichiometry).</li>
      <li><strong>Cumulative impact</strong> — Running total of estimated alumina injected into the upper atmosphere by confirmed re-entries.</li>
    </ul>

    <h3>Cybersecurity &amp; Astronomical Monitoring</h3>
    <p>Cyber: CERT/CC and national CERT advisories, vendor bulletins, and threat-intelligence publications scoped to Starlink hardware, firmware, and infrastructure.
    Astronomical: optical streak reports, RFI notes, and observatory mitigation updates from survey science publications.</p>

    <h3>Why "Quiet" Days Are Still Logged</h3>
    <p>Each digest date is recorded even with no new developments — it provides a continuous audit trail, distinguishes genuine low-activity periods from monitoring gaps, and supports future trend analysis.</p>

    <hr>
    <h3>Data Sources</h3>
    <ul>
      {sources_html}
    </ul>
    <p class="muted">All assumptions and mass-mix parameters are editable in <code>data/starlink_config.yml</code>.</p>
  </section>

{global_archive_html}

{domain_archives_html}

  <style>
    /* archive domain pill colour helpers */
    .archive-domain {{
      display:inline-block;
    }}
    /* keep digest-summary table in case it appears from older builds */
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
    print(f"Site built: {SITE / 'index.html'}")

if __name__ == "__main__":
    build()
