#!/usr/bin/env python3
# Starlink Watch — static site builder with inline citations
import json, html, re, datetime
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

def latest_digest():
    fs = sorted(EVENTS.glob("* — Starlink Daily Digest.md"))
    return fs[-1] if fs else None

# tiny markdown-to-HTML for the digest (headings, lists, links, paragraphs)
_link = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
def md2html(md):
    lines = [ln.rstrip() for ln in md.splitlines()]
    out, buf = [], []
    def flush():
        if not buf: return
        block = "\n".join(buf).strip(); buf.clear()
        if not block: return
        if block.startswith("### "): out.append(f"<h3>{html.escape(block[4:])}</h3>"); return
        if block.startswith("## "):  out.append(f"<h2>{html.escape(block[3:])}</h2>"); return
        if block.startswith("- "):
            li=[]
            for b in block.split("\n"):
                if b.strip().startswith("- "):
                    t = b.strip()[2:]
                    t = _link.sub(r'<a href="\2" target="_blank" rel="noopener">\1</a>', html.escape(t, False))
                    li.append(f"<li>{t}</li>")
            out.append("<ul>\n"+"\n".join(li)+"\n</ul>"); return
        t = _link.sub(r'<a href="\2" target="_blank" rel="noopener">\1</a>', html.escape(block, False))
        out.append(f"<p>{t}</p>")
    for ln in lines:
        if ln.strip(): buf.append(ln)
        else: flush()
    flush()
    return "\n".join(out)

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

    # latest digest
    digest_file = latest_digest()
    digest_html = ""
    if digest_file:
        digest_html = md2html(digest_file.read_text(encoding="utf-8"))

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

  {"<section class='card' style='margin-top:16px'><h2>Latest Digest</h2>"+md2html(latest_digest().read_text(encoding='utf-8'))+"</section>" if latest_digest() else ""}

  <section class="card" style="margin-top:16px">
    <h2>Data Sources</h2>
    <ul>
      <li>CelesTrak Starlink GP/CSV (active elements & counts):
        <a href="{html.escape(src_gp)}" target="_blank">link</a></li>
      <li>CelesTrak SATCAT — Recently Decayed (accumulated Starlink decays):
        <a href="{html.escape(src_decayed)}" target="_blank">link</a></li>
      <li>Generation mass mix & alumina model assumptions:
        <code>data/starlink_config.yml</code> in this repository.</li>
    </ul>
  </section>
</main>

<footer><div class="wrap muted">
  Starlink-only; prioritizes criticisms, risks, and concrete events. Charts update on each run.
</div></footer>
</body></html>"""
    (SITE / "index.html").write_text(page, encoding="utf-8")

if __name__ == "__main__":
    build()
