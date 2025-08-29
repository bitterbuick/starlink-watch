#!/usr/bin/env python3
import re, html, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VAULT = REPO_ROOT / "Starlink Watch"
EVENTS = VAULT / "Events"
ARCHIVE = VAULT / "Archive"
OUT = REPO_ROOT / "site"

# ----- tiny markdown renderer (headings, lists, links, paragraphs) -----
_link_rx = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
def md_to_html(md: str) -> str:
    lines = md.strip().splitlines()
    # drop YAML if present
    out = []
    in_yaml = False
    for ln in lines:
        if ln.strip() == "---":
            in_yaml = not in_yaml
            continue
        if in_yaml: 
            continue
        out.append(ln.rstrip())
    blocks, buf = [], []
    def flush():
        if not buf:
            return
        block = "\n".join(buf).strip()
        buf.clear()
        if not block:
            return
        # headings
        if block.startswith("### "):
            blocks.append(f"<h3>{html.escape(block[4:])}</h3>")
            return
        if block.startswith("## "):
            blocks.append(f"<h2>{html.escape(block[3:])}</h2>")
            return
        # lists
        if block.startswith("- "):
            li = []
            for b in block.split("\n"):
                if b.strip().startswith("- "):
                    text = b.strip()[2:]
                    text = _link_rx.sub(r'<a href="\2" target="_blank" rel="noopener">\1</a>', html.escape(text, quote=False))
                    li.append(f"<li>{text}</li>")
            blocks.append("<ul>\n" + "\n".join(li) + "\n</ul>")
            return
        # paragraph (with links)
        text = _link_rx.sub(r'<a href="\2" target="_blank" rel="noopener">\1</a>', html.escape(block, quote=False))
        blocks.append(f"<p>{text}</p>")
    for ln in out:
        if not ln.strip():
            flush()
        else:
            buf.append(ln)
    flush()
    return "\n".join(blocks)

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
    return p.read_text(encoding="utf-8") if p.exists() else f"# {name} — Archive\n"

def archive_ul(md):
    items = []
    for ln in md.splitlines():
        s = ln.strip()
        if s.startswith("- "):
            s = s[2:]
            s = _link_rx.sub(r'<a href="\2" target="_blank" rel="noopener">\1</a>', html.escape(s, quote=False))
            items.append(f"<li>{s}</li>")
    return "<ul>\n" + "\n".join(items[-40:]) + "\n</ul>" if items else "<p><em>No entries yet.</em></p>"
# ----------------------------------------------------------------------

def build():
    OUT.mkdir(exist_ok=True, parents=True)
    f, digest_md = latest_digest()
    if not digest_md:
        (OUT / "index.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>Starlink Watch</title>"
            "<h1>Starlink Watch</h1><p>No digest yet. Check back soon.</p>", encoding="utf-8")
        return

    title = f.name
    built = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    envA = read_archive("Environmental")
    cybA = read_archive("Cybersecurity")
    astA = read_archive("Astronomical")

    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Starlink Watch — Dashboard</title>
<style>
  :root {{ --bg:#0b1220; --fg:#e5e7eb; --muted:#9aa8b5; --card:#0f172a; --ring:#111827; --accent:#60a5fa; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.55 ui-sans-serif,system-ui,Segoe UI,Roboto; }}
  header, footer {{ padding:22px 16px; border-bottom:1px solid var(--ring); }}
  footer {{ border-top:1px solid var(--ring); border-bottom:none; }}
  .wrap {{ max-width:1120px; margin:0 auto; padding:0 16px; }}
  h1,h2,h3 {{ margin:0 0 12px; }}
  .muted {{ color:var(--muted); font-size:.9em; }}
  .grid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); margin:18px 0; }}
  .card {{ background:var(--card); border-radius:14px; padding:18px 20px; box-shadow:0 6px 24px #0008, inset 0 1px 0 #ffffff0f; }}
  a {{ color:var(--accent); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  ul {{ margin:10px 0 0 20px; }}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>Starlink Watch</h1>
    <div class="muted">Latest build: {html.escape(built)} • {html.escape(title)}</div>
  </div>
</header>

<main class="wrap" style="padding:22px 0 36px">
  <section class="card">
    <h2>Latest Digest</h2>
    {md_to_html(digest_md)}
  </section>

  <section class="grid">
    <div class="card">
      <h3>Archive — Environmental</h3>
      {archive_ul(envA)}
    </div>
    <div class="card">
      <h3>Archive — Cybersecurity</h3>
      {archive_ul(cybA)}
    </div>
    <div class="card">
      <h3>Archive — Astronomical</h3>
      {archive_ul(astA)}
    </div>
  </section>
</main>

<footer>
  <div class="wrap muted">
    Starlink-only digest focused on criticisms, risks, and concrete events (environmental, cybersecurity, astronomical). Links open in new tabs.
  </div>
</footer>
</body></html>"""
    (OUT / "index.html").write_text(page, encoding="utf-8")

if __name__ == "__main__":
    build()
