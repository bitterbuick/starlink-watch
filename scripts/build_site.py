#!/usr/bin/env python3
import os, re, html, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VAULT = REPO_ROOT / "Starlink Watch"
EVENTS = VAULT / "Events"
ARCHIVE = VAULT / "Archive"
OUT = REPO_ROOT / "site"

def latest_digest():
    if not EVENTS.exists():
        return None, None
    files = sorted(EVENTS.glob("* — Starlink Daily Digest.md"))
    if not files:
        return None, None
    f = files[-1]
    return f, f.read_text(encoding="utf-8")

def read_archive(name):
    p = ARCHIVE / f"{name}.md"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return f"# {name} — Archive\n"

def extract_section(md, heading):
    # Return text under "### {heading}" until next "###"
    rx = re.compile(rf"^###\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^###\s+|\Z)", re.M)
    m = rx.search(md)
    return m.group(1).strip() if m else ""

def md_links_to_html(md_chunk):
    # keep links; escape everything else; split into paragraphs
    def linkify(s):
        return re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    blocks = re.split(r"\n\s*\n", md_chunk.strip())
    out = []
    for b in blocks:
        out.append(f"<p>{linkify(html.escape(b, quote=False))}</p>")
    return "\n".join(out) if out else "<p><em>No notes.</em></p>"

def bullets_to_html(md_chunk):
    items = []
    for ln in md_chunk.splitlines():
        s = ln.strip()
        if s.startswith("- "):
            items.append(f"<li>{html.escape(s[2:])}</li>")
    return "<ul>\n" + "\n".join(items) + "\n</ul>" if items else "<p><em>No entries.</em></p>"

def archive_list_to_html(md):
    items = []
    for ln in md.splitlines():
        s = ln.strip()
        if s.startswith("- "):
            items.append(f"<li>{html.escape(s[2:])}</li>")
    return "<ul>\n" + "\n".join(items[-30:]) + "\n</ul>" if items else "<p><em>No entries yet.</em></p>"

def build():
    OUT.mkdir(exist_ok=True, parents=True)
    f, digest = latest_digest()
    title = f.name if f else "Starlink Daily Digest"
    created = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # digest sections
    env = extract_section(digest or "", "Environmental")
    cyb = extract_section(digest or "", "Cybersecurity")
    ast = extract_section(digest or "", "Astronomical")

    envA = read_archive("Environmental")
    cybA = read_archive("Cybersecurity")
    astA = read_archive("Astronomical")

    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Starlink Watch — Dashboard</title>
<style>
  :root {{ --bg:#0b1220; --card:#111827; --fg:#e5e7eb; --muted:#93a4b3; --accent:#60a5fa; --ok:#34d399; --warn:#fbbf24; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 ui-sans-serif,system-ui,Segoe UI,Roboto; }}
  header {{ padding:22px 16px; border-bottom:1px solid #1f2937; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:0 16px; }}
  h1,h2,h3 {{ margin:0 0 12px; }}
  .row {{ display:grid; gap:16px; grid-template-columns: repeat(auto-fit,minmax(300px,1fr)); }}
  .card {{ background:var(--card); border-radius:14px; padding:18px 20px; box-shadow:0 1px 4px #0008; }}
  .muted {{ color:var(--muted); font-size:0.9em; }}
  a {{ color:var(--accent); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  ul {{ margin:8px 0 0 20px; }}
  .pill {{ display:inline-block; padding:2px 8px; border-radius:999px; background:#1f2937; color:var(--muted); font-size:12px; margin-left:8px; }}
  footer {{ padding:22px 16px; color:var(--muted); }}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>Starlink Watch <span class="pill">latest digest & archives</span></h1>
    <div class="muted">Built {html.escape(created)} • {html.escape(title)}</div>
  </div>
</header>

<main class="wrap" style="padding:22px 0 36px">
  <section class="row">
    <div class="card">
      <h2>Environmental</h2>
      {md_links_to_html(env)}
    </div>
    <div class="card">
      <h2>Cybersecurity</h2>
      {md_links_to_html(cyb)}
    </div>
    <div class="card">
      <h2>Astronomical</h2>
      {md_links_to_html(ast)}
    </div>
  </section>

  <section style="margin-top:16px" class="row">
    <div class="card">
      <h3>Archive — Environmental</h3>
      {archive_list_to_html(envA)}
    </div>
    <div class="card">
      <h3>Archive — Cybersecurity</h3>
      {archive_list_to_html(cybA)}
    </div>
    <div class="card">
      <h3>Archive — Astronomical</h3>
      {archive_list_to_html(astA)}
    </div>
  </section>
</main>

<footer>
  <div class="wrap">
    <p>Starlink-only digest generated automatically from curated feeds. Links go to external sources.</p>
  </div>
</footer>
</body></html>"""
    (OUT / "index.html").write_text(page, encoding="utf-8")

if __name__ == "__main__":
    build()
