"""Render the Bangla user guide to a styled, offline HTML file.

    python tools/build_user_guide.py

The output ships inside the installer and is opened by Help → ব্যবহার নির্দেশিকা.
It embeds the bundled Noto Sans Bengali font as a data URI so the guide reads
correctly on any Windows machine with no internet connection.

A deliberately small Markdown subset is supported (headings, tables, lists,
blockquotes, fenced code, bold, inline code, links, horizontal rules) — enough
for the guide and nothing that needs a third-party dependency.
"""

from __future__ import annotations

import base64
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "USER_GUIDE_BN.md"
TARGET = ROOT / "docs" / "USER_GUIDE_BN.html"
FONT = ROOT / "retvia" / "assets" / "fonts" / "NotoSansBengali.ttf"

CSS = """
:root { --navy:#1F3A5F; --accent:#0E7C66; --text:#1B2430; --muted:#64748B;
        --border:#E2E8F0; --bg:#F4F6FA; --surface:#FFFFFF; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font-family:'Noto Sans Bengali','Nirmala UI','Segoe UI',sans-serif;
       font-size:16px; line-height:1.85; }
.wrap { max-width:900px; margin:0 auto; padding:32px 24px 80px; }
header.brand { background:var(--navy); color:#fff; padding:28px 24px; }
header.brand .inner { max-width:900px; margin:0 auto; }
header.brand h1 { margin:0; font-size:30px; }
header.brand p { margin:6px 0 0; color:#C7D3E0; font-size:14px; }
article { background:var(--surface); border:1px solid var(--border);
          border-radius:14px; padding:32px 36px; margin-top:24px; }
h1,h2,h3 { color:var(--navy); line-height:1.5; }
h1 { font-size:28px; margin:0 0 8px; }
h2 { font-size:22px; margin:36px 0 12px; padding-bottom:8px;
     border-bottom:2px solid var(--border); }
h3 { font-size:18px; margin:24px 0 8px; }
p { margin:10px 0; }
ul,ol { padding-left:26px; margin:10px 0; }
li { margin:5px 0; }
table { border-collapse:collapse; width:100%; margin:16px 0; font-size:15px; }
th { background:var(--navy); color:#fff; text-align:left; padding:10px 12px;
     font-weight:600; }
td { border-bottom:1px solid var(--border); padding:9px 12px; vertical-align:top; }
tr:nth-child(even) td { background:#F8FAFC; }
code { background:#EEF2F7; padding:2px 6px; border-radius:4px; font-size:14px;
       font-family:'Consolas','Courier New',monospace; }
pre { background:#16273D; color:#E6EDF5; padding:16px 18px; border-radius:10px;
      overflow-x:auto; line-height:1.7; }
pre code { background:transparent; color:inherit; padding:0; }
blockquote { margin:16px 0; padding:12px 18px; background:#FEF3E2;
             border-left:4px solid #B45309; border-radius:0 8px 8px 0; }
blockquote p { margin:0; }
hr { border:none; border-top:1px solid var(--border); margin:28px 0; }
a { color:var(--accent); }
strong { color:var(--navy); }
footer { max-width:900px; margin:24px auto 0; color:var(--muted); font-size:13px;
         text-align:center; }
@media print { body { background:#fff; } article { border:none; padding:0; } }
"""


def inline(text: str) -> str:
    """Escape, then re-apply the small set of inline markers we support."""
    out = html.escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', out)
    out = re.sub(r"&lt;(https?://[^&]+)&gt;", r'<a href="\1">\1</a>', out)
    return out


def convert(markdown: str) -> str:
    lines = markdown.split("\n")
    out: list[str] = []
    index = 0
    list_stack: list[str] = []

    def close_lists() -> None:
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            close_lists()
            index += 1
            block: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(html.escape(lines[index]))
                index += 1
            index += 1
            out.append("<pre><code>" + "\n".join(block) + "</code></pre>")
            continue

        if stripped.startswith("|") and index + 1 < len(lines) and re.match(
            r"^\|[\s:|-]+\|$", lines[index + 1].strip()
        ):
            close_lists()
            headers = [c.strip() for c in stripped.strip("|").split("|")]
            out.append("<table><thead><tr>")
            out.extend(f"<th>{inline(h)}</th>" for h in headers)
            out.append("</tr></thead><tbody>")
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = [c.strip() for c in lines[index].strip().strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
                index += 1
            out.append("</tbody></table>")
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_lists()
            level = len(heading[1])
            out.append(f"<h{level}>{inline(heading[2])}</h{level}>")
            index += 1
            continue

        if stripped in ("---", "***", "___"):
            close_lists()
            out.append("<hr>")
            index += 1
            continue

        if stripped.startswith(">"):
            close_lists()
            quote: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(inline(lines[index].strip().lstrip(">").strip()))
                index += 1
            out.append("<blockquote><p>" + "<br>".join(quote) + "</p></blockquote>")
            continue

        ordered = re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        if ordered or bullet:
            kind = "ol" if ordered else "ul"
            if not list_stack or list_stack[-1] != kind:
                close_lists()
                out.append(f"<{kind}>")
                list_stack.append(kind)
            content = ordered[2] if ordered else bullet[1]
            out.append(f"<li>{inline(content)}</li>")
            index += 1
            continue

        if not stripped:
            close_lists()
            index += 1
            continue

        close_lists()
        paragraph = [inline(stripped)]
        index += 1
        while index < len(lines):
            nxt = lines[index].strip()
            if (
                not nxt
                or nxt.startswith(("#", "|", ">", "```", "- ", "* ", "+ "))
                or re.match(r"^\d+[.)]\s", nxt)
                or nxt in ("---", "***", "___")
            ):
                break
            paragraph.append(inline(nxt))
            index += 1
        out.append("<p>" + "<br>".join(paragraph) + "</p>")

    close_lists()
    return "\n".join(out)


def main() -> int:
    if not SOURCE.is_file():
        raise SystemExit(f"ERROR: {SOURCE} not found")
    body = convert(SOURCE.read_text(encoding="utf-8"))
    font_css = ""
    if FONT.is_file():
        encoded = base64.b64encode(FONT.read_bytes()).decode("ascii")
        font_css = (
            "@font-face { font-family:'Noto Sans Bengali'; font-style:normal; "
            "font-weight:100 900; font-display:swap; "
            f"src:url(data:font/ttf;base64,{encoded}) format('truetype'); }}\n"
        )
    document = f"""<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Retvia ব্যবহার নির্দেশিকা</title>
<style>
{font_css}{CSS}
</style>
</head>
<body>
<header class="brand"><div class="inner">
  <h1>Retvia ব্যবহার নির্দেশিকা</h1>
  <p>MERQO · সম্পূর্ণ অফলাইন রিটেইল ম্যানেজমেন্ট সিস্টেম · প্রতিষ্ঠাতা শোহান খান</p>
</div></header>
<div class="wrap">
<article>
{body}
</article>
<footer>যোগাযোগ: merqoonline@gmail.com · এই নির্দেশিকা ইন্টারনেট ছাড়াই পড়া যায়।</footer>
</div>
</body>
</html>
"""
    TARGET.write_text(document, encoding="utf-8")
    print(f"Wrote {TARGET.relative_to(ROOT)} ({TARGET.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
