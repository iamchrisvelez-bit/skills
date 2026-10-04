"""Media and document rendering with no required third-party dependencies.

- Markdown -> standalone HTML document (always available)
- Markdown -> PDF (when `reportlab` is installed)
- Pixel art (palette + character grid) -> PNG, written with zlib directly
- Raw SVG -> file
"""

from __future__ import annotations

import html
import re
import struct
import zlib
from pathlib import Path

PAGE_CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1f;--muted:#5b5b66;--accent:#4b3fd1;--code:#f0eee8}
@media (prefers-color-scheme:dark){:root{--bg:#141418;--fg:#ececf1;--muted:#a0a0ad;--accent:#9d94ff;--code:#202028}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,sans-serif}
main{max-width:46rem;margin:0 auto;padding:2.5rem 1rem 4rem}
h1,h2,h3{line-height:1.25}h1{font-size:2rem}a{color:var(--accent)}
code,pre{font-family:ui-monospace,Menlo,monospace;background:var(--code);border-radius:4px}
code{padding:.1em .3em}pre{padding:1rem;overflow-x:auto}pre code{padding:0}
blockquote{margin:0;padding-left:1rem;border-left:3px solid var(--accent);color:var(--muted)}
table{border-collapse:collapse}td,th{border:1px solid var(--muted);padding:.3rem .6rem}
"""


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![*\w])\*([^*]+)\*(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)
    return text


def markdown_to_html(md: str) -> str:
    """A small, predictable Markdown subset: headings, lists, code, quotes, tables."""
    out: list[str] = []
    lines = md.splitlines()
    i = 0
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush()
            i += 1
            code: list[str] = []
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
        elif m := re.match(r"(#{1,6})\s+(.*)", line):
            flush()
            n = len(m.group(1))
            out.append(f"<h{n}>{_inline(m.group(2))}</h{n}>")
        elif re.match(r"\s*([-*]|\d+\.)\s+", line):
            flush()
            ordered = bool(re.match(r"\s*\d+\.", line))
            tag = "ol" if ordered else "ul"
            items = []
            while i < len(lines) and re.match(r"\s*([-*]|\d+\.)\s+", lines[i]):
                item = _inline(re.sub(r"^\s*([-*]|\d+\.)\s+", "", lines[i]))
                items.append(f"<li>{item}</li>")
                i += 1
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue
        elif line.startswith(">"):
            flush()
            out.append(f"<blockquote>{_inline(line.lstrip('> '))}</blockquote>")
        elif line.startswith("|") and i + 1 < len(lines) and re.match(r"\|?\s*:?-{3,}", lines[i + 1]):
            flush()
            head = [c.strip() for c in line.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            th = "".join(f"<th>{_inline(c)}</th>" for c in head)
            trs = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>")
            continue
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
        i += 1
    flush()
    return "\n".join(out)


def render_document(title: str, markdown: str, dest: Path, fmt: str = "html") -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "pdf":
        try:
            return _render_pdf(title, markdown, dest.with_suffix(".pdf"))
        except ImportError:
            fmt = "html"  # graceful fallback; caller sees the .html suffix
    if fmt == "md":
        path = dest.with_suffix(".md")
        path.write_text(markdown, encoding="utf-8")
        return path
    body = markdown_to_html(markdown)
    doc = (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{PAGE_CSS}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )
    path = dest.with_suffix(".html")
    path.write_text(doc, encoding="utf-8")
    return path


def _render_pdf(title: str, markdown: str, path: Path) -> Path:
    from reportlab.lib.pagesizes import letter  # type: ignore
    from reportlab.lib.styles import getSampleStyleSheet  # type: ignore
    from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer  # type: ignore

    styles = getSampleStyleSheet()
    story = []
    in_code, code = False, []
    for line in markdown.splitlines():
        if line.startswith("```"):
            if in_code:
                story.append(Preformatted("\n".join(code), styles["Code"]))
                code = []
            in_code = not in_code
            continue
        if in_code:
            code.append(line)
        elif m := re.match(r"(#{1,3})\s+(.*)", line):
            story.append(Paragraph(_inline(m.group(2)), styles[f"Heading{len(m.group(1))}"]))
        elif line.strip():
            story.append(Paragraph(_inline(line), styles["BodyText"]))
        else:
            story.append(Spacer(1, 6))
    SimpleDocTemplate(str(path), pagesize=letter, title=title).build(story)
    return path


# ------------------------------------------------------------------ pixel art
def _hex(c: str) -> tuple[int, int, int, int]:
    c = c.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    a = int(c[6:8], 16) if len(c) == 8 else 255
    return r, g, b, a


def render_pixel_art(rows: list[str], palette: dict[str, str], dest: Path, scale: int = 8) -> Path:
    """Render a sprite given as rows of palette keys. '.' or ' ' is transparent."""
    if not rows:
        raise ValueError("rows must not be empty")
    width = max(len(r) for r in rows)
    colors = {k: _hex(v) for k, v in palette.items()}
    clear = (0, 0, 0, 0)
    raw = bytearray()
    for row in rows:
        line = bytearray()
        for x in range(width):
            ch = row[x] if x < len(row) else "."
            px = clear if ch in ". " else colors.get(ch)
            if px is None:
                raise ValueError(f"palette has no colour for {ch!r}")
            line += bytes(px) * scale
        for _ in range(scale):
            raw += b"\x00" + line
    w, h = width * scale, len(rows) * scale

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    dest = dest.with_suffix(".png")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(png)
    return dest


def render_svg(svg: str, dest: Path) -> Path:
    if "<svg" not in svg:
        raise ValueError("content is not an SVG document")
    dest = dest.with_suffix(".svg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(svg, encoding="utf-8")
    return dest
