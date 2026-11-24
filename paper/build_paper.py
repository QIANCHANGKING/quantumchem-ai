"""Compile paper/QuantumChem_AI_Paper.md into publication-grade HTML and A4 PDF."""

from __future__ import annotations

import base64
import html
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

PAPER_DIR = Path(__file__).resolve().parent
MD_PATH = PAPER_DIR / "QuantumChem_AI_Paper.md"
HTML_PATH = PAPER_DIR / "QuantumChem_AI_Paper.html"
PDF_PATH = PAPER_DIR / "QuantumChem_AI_Paper.pdf"

_TEX_SYMBOLS: tuple[tuple[str, str], ...] = (
    (r"\langle ", "⟨"),
    (r"\langle", "⟨"),
    (r" \rangle", "⟩"),
    (r"\rangle", "⟩"),
    (r"\left|", "|"),
    (r"\right|", "|"),
    (r"\vert", "|"),
    (r"\leftrightarrow", "↔"),
    (r"\rightarrow", "→"),
    (r"\leftarrow", "←"),
    (r"\Delta", "Δ"),
    (r"\sum", "∑"),
    (r"\alpha", "α"),
    (r"\beta", "β"),
    (r"\mathcal{O}", "O"),
    (r"\zeta", "ζ"),
    (r"\mu", "μ"),
    (r"\sigma", "σ"),
    (r"\approx", "≈"),
    (r"\neq", "≠"),
    (r"\pm", "±"),
    (r"\ge", "≥"),
    (r"\le", "≤"),
    (r"\in", "∈"),
    (r"\infty", "∞"),
    (r"\bmod", " mod "),
    (r"\cdot", "·"),
    (r"\times", "×"),
    (r"\qquad", "\u2003\u2003"),
    (r"\quad", "\u2003"),
    (r"\;", "\u2002"),
    (r"\,", " "),
    (r"\{", "{"),
    (r"\}", "}"),
    (r"\%", "%"),
)

_ITALIC_VARS = frozenset(
    {"E", "S", "M", "q", "Z", "N", "n", "m", "k", "i", "j", "f", "s", "R", "A", "B", "D"}
)


def _extract_braced(s: str, start: int) -> tuple[str, int] | None:
    if start >= len(s) or s[start] != "{":
        return None
    depth = 0
    for idx in range(start, len(s)):
        if s[idx] == "{":
            depth += 1
        elif s[idx] == "}":
            depth -= 1
            if depth == 0:
                return s[start + 1 : idx], idx + 1
    return None


def _replace_macro_pair(s: str, macro: str, fmt: Any) -> str:
    while True:
        pos = s.find(macro + "{")
        if pos == -1:
            break
        first = _extract_braced(s, pos + len(macro))
        if first is None:
            break
        arg1, end_pos = first
        if macro in (r"\dfrac", r"\frac"):
            second = _extract_braced(s, end_pos)
            if second is None:
                break
            arg2, end_pos = second
            rep = fmt(arg1, arg2)
        else:
            rep = fmt(arg1)
        s = s[:pos] + rep + s[end_pos:]
    return s


def _tex_to_html(expr: str) -> str:
    """Convert inline/display TeX formulas into crisp upright/math HTML without raw escapes."""
    holds: list[str] = []

    def _hold(snippet: str) -> str:
        idx = len(holds)
        holds.append(snippet)
        return f"@@TH{idx}@@"

    def _convert(chunk: str) -> str:
        raw = chunk.strip()
        raw = _replace_macro_pair(
            raw,
            r"\dfrac",
            lambda a, b: _hold(
                '<span class="frac">'
                f'<span class="num">{_convert(a)}</span>'
                f'<span class="den">{_convert(b)}</span>'
                "</span>"
            ),
        )
        raw = _replace_macro_pair(
            raw,
            r"\frac",
            lambda a, b: _hold(
                '<span class="frac">'
                f'<span class="num">{_convert(a)}</span>'
                f'<span class="den">{_convert(b)}</span>'
                "</span>"
            ),
        )
        raw = _replace_macro_pair(
            raw, r"\text", lambda t: _hold(f'<span class="rm">{html.escape(t)}</span>')
        )
        raw = _replace_macro_pair(
            raw, r"\mathbf", lambda t: _hold(f'<b class="rm">{html.escape(t)}</b>')
        )

        def _conv_script(prefix: str, tag: str, txt: str) -> str:
            out = txt
            while True:
                pos = out.find(prefix + "{")
                if pos == -1:
                    break
                grp = _extract_braced(out, pos + len(prefix))
                if grp is None:
                    break
                inner, end_pos = grp
                out = out[:pos] + _hold(f"<{tag}>{_convert(inner)}</{tag}>") + out[end_pos:]
            return out

        raw = _conv_script("_", "sub", raw)
        raw = _conv_script("^", "sup", raw)

        for k, v in _TEX_SYMBOLS:
            raw = raw.replace(k, v)

        raw = re.sub(r"_([A-Za-z0-9])", lambda m: _hold(f"<sub>{_convert(m.group(1))}</sub>"), raw)
        raw = re.sub(
            r"\^([A-Za-z0-9+\-−])", lambda m: _hold(f"<sup>{html.escape(m.group(1))}</sup>"), raw
        )

        def _style_vars(m: re.Match[str]) -> str:
            tok = m.group(0)
            return f"<i>{tok}</i>" if tok in _ITALIC_VARS else tok

        parts = re.split(r"(@@TH\d+@@)", raw)
        styled_parts: list[str] = []
        for part in parts:
            if part.startswith("@@TH") and part.endswith("@@"):
                styled_parts.append(part)
            else:
                esc = html.escape(part).replace(" - ", " − ").replace("(-", "(−")
                esc = re.sub(r"(?<=[\w\}])-(?=[A-Za-z0-9])", "−", esc)
                esc = re.sub(r"\b[A-Za-z]\b", _style_vars, esc)
                styled_parts.append(esc)
        return "".join(styled_parts)

    rendered = _convert(expr)
    # Expand nested placeholders cleanly until none remain
    while "@@TH" in rendered:
        prev = rendered
        for idx, snippet in enumerate(holds):
            rendered = rendered.replace(f"@@TH{idx}@@", snippet)
        if rendered == prev:
            break
    nowrap_cls = " math-nowrap" if len(expr) <= 28 else ""
    return f'<span class="math{nowrap_cls}">{rendered}</span>'


def _inline_md(text: str) -> str:
    """Render inline markdown: math, images, code spans, bold, and italics."""
    math_tokens: list[str] = []

    def _hold_math(m: re.Match[str]) -> str:
        idx = len(math_tokens)
        math_tokens.append(_tex_to_html(m.group(1)))
        return f"@@MATH{idx}@@"

    text = re.sub(r"\$([^$\n]+)\$", _hold_math, text)

    img_tokens: list[str] = []

    def _hold_img(m: re.Match[str]) -> str:
        alt, rel = m.group(1), m.group(2)
        fpath = (PAPER_DIR / rel).resolve()
        if fpath.suffix.lower() == ".svg" and fpath.exists():
            tag = f'<div class="svg-wrap">{fpath.read_text(encoding="utf-8")}</div>'
        elif fpath.exists():
            b64 = base64.b64encode(fpath.read_bytes()).decode("ascii")
            mime = "image/png" if fpath.suffix.lower() == ".png" else "image/jpeg"
            tag = f'<img class="fig-img" src="data:{mime};base64,{b64}" alt="{html.escape(alt)}"/>'
        else:
            tag = f"<em>[Missing figure: {html.escape(rel)}]</em>"
        idx = len(img_tokens)
        img_tokens.append(tag)
        return f"@@IMG{idx}@@"

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _hold_img, text)

    code_tokens: list[str] = []

    def _hold_code(m: re.Match[str]) -> str:
        idx = len(code_tokens)
        code_tokens.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"@@CODE{idx}@@"

    text = re.sub(r"`([^`]+)`", _hold_code, text)

    out = html.escape(text)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", out)

    for idx, tok in enumerate(code_tokens):
        out = out.replace(f"@@CODE{idx}@@", tok)
    for idx, tok in enumerate(math_tokens):
        out = out.replace(f"@@MATH{idx}@@", tok)
    for idx, tok in enumerate(img_tokens):
        out = out.replace(f"@@IMG{idx}@@", tok)
    return out


def _md_to_html_body(md: str) -> str:
    lines = md.splitlines()
    blocks: list[str] = []
    i = 0
    n = len(lines)
    in_references = False
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped == "---":
            blocks.append("<hr/>")
            i += 1
            continue
        if stripped.startswith("# "):
            blocks.append(f'<h1 class="paper-title">{_inline_md(stripped[2:])}</h1>')
            i += 1
            continue
        if stripped.startswith("## "):
            title_txt = stripped[3:].strip()
            in_references = title_txt.startswith("参考文献")
            blocks.append(f"<h2>{_inline_md(title_txt)}</h2>")
            i += 1
            continue
        if stripped.startswith("### "):
            blocks.append(f"<h3>{_inline_md(stripped[4:])}</h3>")
            i += 1
            continue

        # Fenced algorithm / code block
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            code_lines: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            if lang == "algorithm":
                title_line = code_lines[0] if code_lines else "Algorithm"
                body_lines = code_lines[1:] if len(code_lines) > 1 else []
                body_html = "<br/>".join(_inline_md(ln) for ln in body_lines)
                blocks.append(
                    '<div class="algo-box">'
                    f'<div class="algo-hdr">{_inline_md(title_line)}</div>'
                    f'<div class="algo-body">{body_html}</div>'
                    "</div>"
                )
            else:
                blocks.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
            continue

        # Numbered display equation: $$ expr $$ (k)
        eq_m = re.match(r"^\$\$(.+)\$\$(?:\s*\((\d+)\))?$", stripped)
        if eq_m:
            expr_html = _tex_to_html(eq_m.group(1))
            num_html = f'<div class="eq-num">({eq_m.group(2)})</div>' if eq_m.group(2) else ""
            blocks.append(
                f'<div class="eq-row"><div class="eq-body">{expr_html}</div>{num_html}</div>'
            )
            i += 1
            continue

        # Markdown Table
        if stripped.startswith("|") and i + 1 < n and lines[i + 1].strip().startswith("|"):
            tbl_lines: list[str] = []
            while i < n and lines[i].strip().startswith("|"):
                tbl_lines.append(lines[i].strip())
                i += 1
            header_cells = [
                c.strip().replace(r"\|", "|")
                for c in re.split(r"(?<!\\)\|", tbl_lines[0].strip("|"))
            ]
            align_cells = [c.strip() for c in re.split(r"(?<!\\)\|", tbl_lines[1].strip("|"))]
            body_rows = [
                [c.strip().replace(r"\|", "|") for c in re.split(r"(?<!\\)\|", row.strip("|"))]
                for row in tbl_lines[2:]
            ]

            def _align_cls(idx: int, cells: list[str]) -> str:
                tok = cells[idx] if idx < len(cells) else "---"
                if tok.startswith(":") and tok.endswith(":"):
                    return ' class="center"'
                if tok.endswith(":"):
                    return ' class="num"'
                return ""

            ths = "".join(
                f"<th{_align_cls(c_i, align_cells)}>{_inline_md(c)}</th>"
                for c_i, c in enumerate(header_cells)
            )
            trs = "".join(
                "<tr>"
                + "".join(
                    f"<td{_align_cls(c_i, align_cells)}>{_inline_md(c)}</td>"
                    for c_i, c in enumerate(r)
                )
                + "</tr>"
                for r in body_rows
            )
            blocks.append(f"<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>")
            continue

        # Unordered list
        if stripped.startswith("- "):
            items: list[str] = []
            while i < n and lines[i].strip().startswith("- "):
                items.append(f"<li>{_inline_md(lines[i].strip()[2:])}</li>")
                i += 1
            blocks.append(f"<ul>{''.join(items)}</ul>")
            continue

        # Ordered list (preserve start number across interrupted sections)
        if m_ol := re.match(r"^(\d+)\.\s+", stripped):
            start_num = int(m_ol.group(1))
            items = []
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                items.append(f"<li>{_inline_md(re.sub(r'^\d+\.\s+', '', lines[i].strip()))}</li>")
                i += 1
            start_attr = f' start="{start_num}"' if start_num != 1 else ""
            blocks.append(f"<ol{start_attr}>{''.join(items)}</ol>")
            continue

        # Standalone figure + optional immediate caption
        if stripped.startswith("!["):
            fig_html = _inline_md(stripped)
            cap_html = ""
            if i + 2 < n and not lines[i + 1].strip() and lines[i + 2].strip().startswith("*图 "):
                cap_txt = lines[i + 2].strip().strip("*")
                cap_html = f'<p class="fig-caption">{_inline_md(cap_txt)}</p>'
                i += 3
            elif i + 1 < n and lines[i + 1].strip().startswith("*图 "):
                cap_txt = lines[i + 1].strip().strip("*")
                cap_html = f'<p class="fig-caption">{_inline_md(cap_txt)}</p>'
                i += 2
            else:
                i += 1
            blocks.append(f'<div class="figure-block">{fig_html}{cap_html}</div>')
            continue

        # Table caption right above table (*表 N：...*)
        if stripped.startswith("*表 ") and stripped.endswith("*"):
            blocks.append(f'<p class="table-caption">{_inline_md(stripped[1:-1])}</p>')
            i += 1
            continue

        # Standalone figure caption fallback
        if stripped.startswith("*图 ") and stripped.endswith("*"):
            blocks.append(f'<p class="fig-caption">{_inline_md(stripped[1:-1])}</p>')
            i += 1
            continue

        # Normal paragraph (join consecutive prose lines)
        para_lines = [stripped]
        i += 1
        while (
            i < n
            and lines[i].strip()
            and not lines[i]
            .strip()
            .startswith(("#", "|", "- ", "---", "![", "```", "$$", "*表 ", "*图 "))
            and not re.match(r"^\d+\.\s+", lines[i].strip())
        ):
            para_lines.append(lines[i].strip())
            i += 1
        p_text = " ".join(para_lines)
        if in_references and p_text.startswith("["):
            cls = ' class="ref-item"'
        elif p_text.startswith("**QuantumChem AI:"):
            cls = ' class="subtitle-en"'
        elif p_text.startswith("**钱昌天**") or p_text.startswith("**作者"):
            cls = ' class="author-zh"'
        elif p_text.startswith("（首都师范大学"):
            cls = ' class="affil-zh"'
        elif p_text.startswith("Changtian Qian"):
            cls = ' class="affil-en"'
        elif p_text.startswith("**QuantumChem AI 研发"):
            cls = ' class="authors"'
        elif p_text.startswith("**关键词") or p_text.startswith("**Keywords"):
            cls = ' class="keywords"'
        elif re.search(r"[\u4e00-\u9fff]", p_text):
            cls = ' class="prose-zh"'
        else:
            cls = ' class="prose-en"'
        blocks.append(f"<p{cls}>{_inline_md(p_text)}</p>")
    return "\n".join(blocks)


def _assert_clean_html(full_html: str) -> None:
    # Strip <style>, <svg>, data URIs, and <code> blocks before checking leftover TeX escapes
    cleaned = re.sub(r"<style>.*?</style>", "", full_html, flags=re.DOTALL)
    cleaned = re.sub(r"<svg.*?</svg>", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"data:image/[a-z]+;base64,[A-Za-z0-9+/=]+", "", cleaned)
    for bad in (
        r"\dfrac",
        r"\frac",
        r"\text{",
        r"\langle",
        r"\rangle",
        r"\sum",
        r"\zeta",
        r"\mathcal",
        r"\quad",
        r"\qquad",
        r"\{",
        r"\}",
        r"\%",
        "@@TH",
    ):
        if bad in cleaned:
            raise AssertionError(f"Unrendered TeX macro leaked into HTML: {bad!r}")
    prose_only = re.sub(r"<code>.*?</code>", "", cleaned, flags=re.DOTALL)
    prose_only = re.sub(r"<[^>]+>", "", prose_only)
    if m := re.search(r"\\[A-Za-z]{2,}", prose_only):
        raise AssertionError(f"Unexpected TeX control sequence in prose HTML: {m.group(0)!r}")


def build_paper() -> tuple[Path, Path]:
    md = MD_PATH.read_text(encoding="utf-8")
    body = _md_to_html_body(md)
    full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>QuantumChem AI 学术论文</title>
<style>
@page {{
    size: A4;
    margin: 17mm 16.5mm 17mm 16.5mm;
}}
body {{
    font-family: "Times New Roman", "Cambria", "STSong", "SimSun", serif;
    font-size: 10.1pt;
    line-height: 1.54;
    color: #111827;
    max-width: 860px;
    margin: 0 auto;
    padding: 2px 6px;
}}
h1.paper-title {{
    font-family: "Microsoft YaHei", "SimHei", "Arial", sans-serif;
    font-size: 16.5pt;
    text-align: center;
    color: #0f2557;
    margin: 4px 0 6px 0;
    line-height: 1.35;
}}
p.subtitle-en {{
    font-family: "Times New Roman", serif;
    font-size: 11.0pt;
    text-align: center;
    color: #334155;
    margin: 2px 0 3px 0;
    line-height: 1.38;
}}
p.author-zh {{
    font-family: "Microsoft YaHei", "SimHei", "SimSun", sans-serif;
    font-size: 11.0pt;
    text-align: center;
    color: #0f172a;
    margin: 2px 0 1px 0;
}}
p.affil-zh {{
    font-family: "SimSun", "Times New Roman", serif;
    font-size: 9.4pt;
    text-align: center;
    color: #475569;
    margin: 0 0 6px 0;
}}
p.affil-en {{
    font-family: "Times New Roman", serif;
    font-style: italic;
    font-size: 9.2pt;
    text-align: center;
    color: #475569;
    margin: 0 0 8px 0;
}}
p.authors {{
    font-family: "Times New Roman", "SimSun", serif;
    font-size: 9.8pt;
    text-align: center;
    color: #475569;
    margin: 0 0 12px 0;
}}
h2 {{
    font-family: "Microsoft YaHei", "SimHei", "Arial", sans-serif;
    font-size: 12.2pt;
    color: #0f2557;
    border-bottom: 1.4pt solid #1e40af;
    padding-bottom: 2px;
    margin-top: 13px;
    margin-bottom: 6px;
    break-after: avoid;
}}
h3 {{
    font-family: "Microsoft YaHei", "SimHei", "Arial", sans-serif;
    font-size: 10.6pt;
    color: #1e3a8a;
    margin-top: 10px;
    margin-bottom: 4px;
    break-after: avoid;
}}
p {{
    margin: 4px 0 5.5px 0;
}}
p.prose-zh {{
    text-align: justify;
    text-justify: inter-ideograph;
}}
p.prose-en {{
    font-family: "Times New Roman", serif;
    text-align: justify;
    hyphens: auto;
}}
p.keywords {{
    font-size: 9.6pt;
    color: #1e293b;
    margin-top: 6px;
    margin-bottom: 10px;
}}
hr {{
    border: none;
    border-top: 0.8pt solid #cbd5e1;
    margin: 10px 0;
}}
code {{
    font-family: "Consolas", "Courier New", monospace;
    font-size: 8.8pt;
    color: #0f172a;
    background: #f8fafc;
    border: 0.5pt solid #e2e8f0;
    padding: 0 3px;
    border-radius: 2px;
}}
ul, ol {{
    margin: 3px 0 6px 0;
    padding-left: 20px;
}}
li {{
    margin-bottom: 2.5px;
    text-align: justify;
}}
p.table-caption {{
    font-family: "Microsoft YaHei", "Arial", sans-serif;
    font-size: 9.2pt;
    font-weight: 700;
    color: #0f2557;
    text-align: center;
    margin: 12px 0 4px 0;
    break-after: avoid;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    margin: 0 0 8px 0;
    font-size: 8.2pt;
    line-height: 1.38;
    page-break-inside: auto;
}}
thead {{
    display: table-header-group;
}}
tr {{
    break-inside: avoid;
}}
th {{
    background: #f1f5f9;
    color: #0f2557;
    border-top: 1.4pt solid #0f2557;
    border-bottom: 0.9pt solid #0f2557;
    padding: 4.5px 5.5px;
    text-align: left;
    font-family: "Microsoft YaHei", "Arial", sans-serif;
    font-weight: 700;
}}
td {{
    border-bottom: 0.5pt solid #cbd5e1;
    padding: 3.5px 5.5px;
    vertical-align: top;
}}
td:first-child, th:first-child {{
    white-space: nowrap;
}}
th.center, td.center {{
    text-align: center;
    white-space: nowrap;
}}
th.num, td.num {{
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
}}
tbody tr:last-child td {{
    border-bottom: 1.4pt solid #0f2557;
}}
.figure-block {{
    text-align: center;
    margin: 7px 0 8px 0;
    break-inside: avoid;
}}
.fig-img {{
    max-width: 89%;
    max-height: 92mm;
    width: auto;
    height: auto;
    display: block;
    margin: 0 auto;
}}
.svg-wrap svg {{
    max-width: 98%;
    height: auto;
    display: block;
    margin: 0 auto;
}}
p.fig-caption {{
    font-family: "Microsoft YaHei", "Arial", sans-serif;
    text-align: center;
    font-size: 9pt;
    color: #334155;
    margin: 5px 0 2px 0;
    break-before: avoid;
}}
.eq-row {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 7px 14px 7px 28px;
    break-inside: avoid;
}}
.eq-body {{
    flex: 1;
    text-align: center;
    font-size: 10.5pt;
}}
.eq-num {{
    width: 44px;
    text-align: right;
    font-size: 9.8pt;
    color: #334155;
}}
.algo-box {{
    border-top: 1.4pt solid #0f2557;
    border-bottom: 1.4pt solid #0f2557;
    background: #fbfdff;
    padding: 7px 12px;
    margin: 10px 0 12px 0;
    break-inside: avoid;
    font-size: 9pt;
}}
.algo-hdr {{
    font-family: "Microsoft YaHei", "Arial", sans-serif;
    font-weight: 700;
    color: #0f2557;
    border-bottom: 0.7pt solid #94a3b8;
    padding-bottom: 3px;
    margin-bottom: 5px;
}}
.algo-body {{
    font-family: "Times New Roman", "SimSun", monospace;
    line-height: 1.5;
}}
.math {{
    font-family: "Times New Roman", "Cambria Math", serif;
    font-style: normal;
}}
.math-nowrap {{
    white-space: nowrap;
}}
.math .rm {{
    font-style: normal;
}}
.frac {{
    display: inline-flex;
    flex-direction: column;
    vertical-align: middle;
    text-align: center;
    font-size: 0.86em;
    line-height: 1.15;
    margin: 0 2px;
}}
.frac .num {{
    border-bottom: 0.8pt solid #111827;
    padding: 0 2px 1px 2px;
    white-space: nowrap;
}}
.frac .den {{
    padding: 1px 2px 0 2px;
    white-space: nowrap;
}}
p.ref-item {{
    font-family: "Times New Roman", "SimSun", serif;
    font-size: 8.2pt;
    line-height: 1.28;
    padding-left: 2.2em;
    text-indent: -2.2em;
    margin: 0 0 1.5px 0;
    text-align: justify;
}}
</style>
</head>
<body>
{body}
</body>
</html>
"""
    _assert_clean_html(full_html)
    HTML_PATH.write_text(full_html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(HTML_PATH.as_uri(), wait_until="networkidle")
        page.pdf(
            path=str(PDF_PATH),
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template='<div style="font-family:Times New Roman,serif;font-size:7.8pt;color:#64748b;width:100%;text-align:center;">Qian, C. · QuantumChem AI: Deterministic Rule-Driven and LLM-Assisted Atomic Cluster Platform</div>',
            footer_template='<div style="font-family:Microsoft YaHei,serif;font-size:7.8pt;color:#64748b;width:100%;text-align:center;">第 <span class="pageNumber"></span> / <span class="totalPages"></span> 页</div>',
            margin={"top": "17mm", "bottom": "17mm", "left": "16.5mm", "right": "16.5mm"},
        )
        browser.close()
    return HTML_PATH, PDF_PATH


if __name__ == "__main__":
    h, p = build_paper()
    print(f"Built HTML ({h.stat().st_size} B) and PDF ({p.stat().st_size} B): {p}")
