#!/usr/bin/env python3
import json, html, re, datetime
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
VAULT = REPO / "Starlink Watch"
EVENTS = VAULT / "Events"
ARCHIVE = VAULT / "Archive"
DATA = REPO / "data"
SITE = REPO / "site"
ASSETS = SITE / "assets"
SITE.mkdir(exist_ok=True, parents=True)
ASSETS.mkdir(exist_ok=True, parents=True)

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

# tiny markdown-to-HTML for the digest
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

def build():
    met = load_metrics()
    # charts
    chart(load_series("active_count"),       "Active Starlink satellites (count)", ASSETS/"active.png")
    chart(load_series("on_orbit_mass_kg"),   "Estimated on-orbit mass (kg)",        ASSETS/"onorbit.png")
    chart(load_series("reentered_mass_kg"),  "Estimated re-entered mass (kg)",      ASSETS/"reentry.png")
    chart(load_series("alumina_kg"),         "Estimated alumina formed (kg)",       ASSETS/"alumina.png")

    # latest digest html (optional box)
    digest_file = latest_digest()
    digest_html = ""
    if digest_file:
        digest_html = md2html(digest_file.read_text(encoding="utf-8"))

    # page
    built = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    tiles = ""
    if met:
        tiles = f"""
        <div class="tiles">
          <div class="tile"><div class="k">{met['active_count']:,}</div><div class="t">Active Starlink</div></div>
          <div class="tile"><div class="k">{met['decayed_total']:,}</div><div class="t">Total decayed</div></div>
          <div class="tile"><div class="k">{met['on_orbit_mass_kg']:,}</div><div class="t">On-orbit mass (kg)</div></div>
          <div class="tile"><div class="k">{met['reentered_mass_kg']:,}</div><div class="t">Re-entered mass (kg)</div></div>
          <div class="tile"><div class="k">{met['alumina_kg']:,}</div><div class="t">Al₂O₃ estimate (kg)</div></div>
        </div>
        """

    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Starlink Watch — Metrics & Digest</title>
<style>
  :root {{ --bg:#0b1220; --fg:#e6edf3; --muted:#9fb0bd; --card:#0f172a; --ring:#1f2937; --accent:#60a5fa; }}
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
  img.chart {{ width:100%; height:auto; border-radius:10px; background:#0d1528; border:1px solid #15233b; padding:6px; }}
  a {{ color:var(--accent); text-decoration:none }} a:hover {{ text-decoration:underline }}
  ul {{ margin:10px 0 0 20px }}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>Starlink Watch — Metrics & Digest</h1>
    <div class="muted">Built {html.escape(built)}</div>
  </div>
</header>

<main class="wrap" style="padding:22px 0 36px">
  <section class="card">
    <h2>Starlink metrics</h2>
    {tiles}
    <div class="grid" style="margin-top:8px">
      <div class="card"><h3>Active satellites</h3><img class="chart" src="assets/active.png" alt=""></div>
      <div class="card"><h3>On-orbit mass (kg)</h3><img class="chart" src="assets/onorbit.png" alt=""></div>
      <div class="card"><h3>Re-entered mass (kg)</h3><img class="chart" src="assets/reentry.png" alt=""></div>
      <div class="card"><h3>Al₂O₃ estimate (kg)</h3><img class="chart" src="assets/alumina.png" alt=""></div>
    </div>
    <p class="muted">Sources: CelesTrak GP Starlink group & SATCAT decays (recent, accumulated). Assumptions documented in repo file <code>data/starlink_config.yml</code>. Adjust to refine.</p>
  </section>

  {"<section class='card' style='margin-top:16px'><h2>Latest Digest</h2>"+digest_html+"</section>" if digest_html else ""}

  <section class="grid" style="margin-top:16px">
    <div class="card"><h3>Archive — Environmental</h3><p>See <code>Starlink Watch/Archive/Environmental.md</code> in the repo/vault.</p></div>
    <div class="card"><h3>Archive — Cybersecurity</h3><p>See <code>Starlink Watch/Archive/Cybersecurity.md</code>.</p></div>
    <div class="card"><h3>Archive — Astronomical</h3><p>See <code>Starlink Watch/Archive/Astronomical.md</code>.</p></div>
  </section>
</main>

<footer><div class="wrap muted">
  Starlink-only; prioritizes criticisms, risks, and concrete events. Charts update on each run.
</div></footer>
</body></html>"""
    (SITE / "index.html").write_text(page, encoding="utf-8")

if __name__ == "__main__":
    build()
