"""Render a Markdown file with Mermaid blocks to a standalone HTML page. Usage: python3 render.py FILE.md"""
import html, pathlib, sys
src = pathlib.Path(sys.argv[1]); md = src.read_text()
page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{src.stem}</title>
<script src="https://cdn.jsdelivr.net/npm/marked@15.0.7/marked.min.js"></script>
<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs";
const text = document.getElementById("src").textContent;
const r = new marked.Renderer();
r.code = ({{text, lang}}) => lang === "mermaid" ? `<pre class="mermaid">${{text}}</pre>` : `<pre><code>${{text.replace(/</g,"&lt;")}}</code></pre>`;
document.getElementById("out").innerHTML = marked.parse(text, {{renderer: r}});
mermaid.initialize({{startOnLoad:false, theme:"neutral", er:{{useMaxWidth:false}}, sequence:{{useMaxWidth:false}}}});
await mermaid.run();
</script>
<style>body{{font:16px/1.5 -apple-system,Helvetica,sans-serif;max-width:1400px;margin:2em auto;padding:0 1em;color:#111}}
table{{border-collapse:collapse;font-size:14px}}td,th{{border:1px solid #ccc;padding:4px 8px;vertical-align:top}}th{{background:#f3f3f3}}
pre.mermaid{{overflow-x:auto;background:#fafafa;padding:1em}}code{{font-size:14px}}</style></head>
<body><script id="src" type="text/plain">{html.escape(md)}</script><div id="out"></div></body></html>"""
src.with_suffix(".html").write_text(page)
