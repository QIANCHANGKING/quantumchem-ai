"""Build release documentation PDF, refresh wheel package, and create clean release ZIP."""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = REPO_ROOT / "dist"
GUIDE_MD_PATH = REPO_ROOT / "使用说明.md"
GUIDE_PDF_PATH = DIST_DIR / "QuantumChem_AI_使用说明.pdf"
RELEASE_ROOT_NAME = "QuantumChem_AI_v0.1.0"
RELEASE_ZIP_PATH = DIST_DIR / f"{RELEASE_ROOT_NAME}_Release.zip"

TOP_LEVEL_FILES: tuple[str, ...] = (
    "使用说明.md",
    "README.md",
    "AGENTS.md",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    ".gitignore",
    "一键安装依赖.bat",
    "启动量子化学助手.bat",
    "启动量子化学助手(仅界面模式).bat",
    "启动量子化学助手(模拟演示).bat",
    "停止量子化学助手.bat",
    "生成桌面快捷方式.bat",
)

INCLUDED_DIRS: tuple[str, ...] = (
    "src",
    "web",
    "scripts",
    "assets",
    ".streamlit",
    "tests/data/golden",
    "tests/data/multiwfn",
)

PAPER_FILES: tuple[str, ...] = (
    "paper/QuantumChem_AI_Paper.pdf",
    "paper/QuantumChem_AI_Paper.md",
    "paper/QuantumChem_AI_Paper.html",
    "paper/build_paper.py",
    "paper/make_paper_figures.py",
    "paper/data/ln_au5_summary.json",
)

FORBIDDEN_DIR_PARTS = frozenset({"__pycache__", ".venv", ".git", "projects", "paper_tmp"})
FORBIDDEN_SUFFIXES = frozenset(
    {".pyc", ".pyo", ".sqlite", ".sqlite3", ".pem", ".fchk", ".cub", ".cube", ".opju"}
)


def _inline_guide_md(text: str) -> str:
    """Render inline Markdown (code spans, links, bold, inline math, safe <br>)."""
    tokens: list[str] = []

    def _hold(snippet: str) -> str:
        idx = len(tokens)
        tokens.append(snippet)
        return f"@@TOK{idx}@@"

    text = re.sub(r"<br\s*/?>", lambda _m: _hold("<br/>"), text)
    text = re.sub(
        r"`([^`]+)`",
        lambda m: _hold(f"<code>{html.escape(m.group(1))}</code>"),
        text,
    )
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: _hold(f'<a href="{html.escape(m.group(2))}">{html.escape(m.group(1))}</a>'),
        text,
    )
    if r"$\mu_B$" in text:
        text = text.replace(r"$\mu_B$", _hold('<span class="math"><i>μ</i><sub>B</sub></span>'))

    escaped = html.escape(text)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    for idx, snippet in enumerate(tokens):
        escaped = escaped.replace(f"@@TOK{idx}@@", snippet)
    return escaped


def _guide_md_to_html_body(md_text: str) -> str:
    """Convert 使用说明.md into clean HTML sections."""
    lines = md_text.splitlines()
    blocks: list[str] = []
    i = 0
    n = len(lines)

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

        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            i += 1
            code_lines: list[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < n:
                i += 1
            cls = f' class="language-{html.escape(lang)}"' if lang else ""
            code_body = html.escape("\n".join(code_lines))
            blocks.append(f"<pre><code{cls}>{code_body}</code></pre>")
            continue

        if stripped.startswith("# "):
            blocks.append(f'<h1 class="doc-title">{_inline_guide_md(stripped[2:])}</h1>')
            i += 1
            continue
        if stripped.startswith("## "):
            blocks.append(f"<h2>{_inline_guide_md(stripped[3:])}</h2>")
            i += 1
            continue
        if stripped.startswith("### "):
            blocks.append(f"<h3>{_inline_guide_md(stripped[4:])}</h3>")
            i += 1
            continue

        if stripped.startswith("> "):
            quote_lines: list[str] = []
            while i < n and lines[i].strip().startswith("> "):
                quote_lines.append(lines[i].strip()[2:])
                i += 1
            blocks.append(
                f'<blockquote class="callout">{_inline_guide_md(" ".join(quote_lines))}</blockquote>'
            )
            continue

        if stripped.startswith("|") and i + 1 < n and lines[i + 1].strip().startswith("|"):
            tbl_lines: list[str] = []
            while i < n and lines[i].strip().startswith("|"):
                tbl_lines.append(lines[i].strip())
                i += 1
            headers = [
                c.strip().replace(r"\|", "|")
                for c in re.split(r"(?<!\\)\|", tbl_lines[0].strip("|"))
            ]
            rows = [
                [c.strip().replace(r"\|", "|") for c in re.split(r"(?<!\\)\|", row.strip("|"))]
                for row in tbl_lines[2:]
            ]
            ths = "".join(f"<th>{_inline_guide_md(h)}</th>" for h in headers)
            trs = "".join(
                "<tr>" + "".join(f"<td>{_inline_guide_md(cell)}</td>" for cell in row) + "</tr>"
                for row in rows
            )
            blocks.append(f"<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>")
            continue

        if stripped.startswith("- "):
            items: list[str] = []
            while i < n and (lines[i].strip().startswith("- ") or lines[i].startswith("  ")):
                if lines[i].strip().startswith("- "):
                    items.append(lines[i].strip()[2:])
                elif items:
                    sub = lines[i].strip()
                    if sub.startswith("```"):
                        items[-1] += "\n" + sub
                        i += 1
                        while i < n and not lines[i].strip().startswith("```"):
                            items[-1] += "\n" + lines[i].strip()
                            i += 1
                        if i < n:
                            items[-1] += "\n" + lines[i].strip()
                            i += 1
                        continue
                    items[-1] += " " + sub
                i += 1
            li_html: list[str] = []
            for item in items:
                if "```" in item:
                    before, rest = item.split("```", 1)
                    code_part, *after_parts = rest.split("```", 1)
                    code_lines_sub = code_part.strip().splitlines()
                    if code_lines_sub and re.fullmatch(
                        r"[A-Za-z0-9_-]+", code_lines_sub[0].strip()
                    ):
                        code_lines_sub = code_lines_sub[1:]
                    snippet = html.escape("\n".join(code_lines_sub))
                    after_txt = after_parts[0].strip() if after_parts else ""
                    li_html.append(
                        f"<li>{_inline_guide_md(before.strip())}"
                        f"<pre><code>{snippet}</code></pre>"
                        f"{_inline_guide_md(after_txt)}</li>"
                    )
                else:
                    li_html.append(f"<li>{_inline_guide_md(item)}</li>")
            blocks.append(f"<ul>{''.join(li_html)}</ul>")
            continue

        if m_ol := re.match(r"^(\d+)\.\s+", stripped):
            start_num = int(m_ol.group(1))
            ol_items: list[str] = []
            while i < n and (
                re.match(r"^\d+\.\s+", lines[i].strip()) or lines[i].startswith("   ")
            ):
                cur = lines[i].strip()
                if re.match(r"^\d+\.\s+", cur):
                    ol_items.append(re.sub(r"^\d+\.\s+", "", cur))
                elif ol_items:
                    if cur.startswith("```"):
                        ol_items[-1] += "\n" + cur
                        i += 1
                        while i < n and not lines[i].strip().startswith("```"):
                            ol_items[-1] += "\n" + lines[i].strip()
                            i += 1
                        if i < n:
                            ol_items[-1] += "\n" + lines[i].strip()
                            i += 1
                        continue
                    ol_items[-1] += " " + cur
                i += 1
            ol_li_html: list[str] = []
            for item in ol_items:
                if "```" in item:
                    before, rest = item.split("```", 1)
                    code_part, *after_parts = rest.split("```", 1)
                    code_lines_sub = code_part.strip().splitlines()
                    if code_lines_sub and re.fullmatch(
                        r"[A-Za-z0-9_-]+", code_lines_sub[0].strip()
                    ):
                        code_lines_sub = code_lines_sub[1:]
                    snippet = html.escape("\n".join(code_lines_sub))
                    ol_li_html.append(
                        f"<li>{_inline_guide_md(before.strip())}<pre><code>{snippet}</code></pre></li>"
                    )
                else:
                    ol_li_html.append(f"<li>{_inline_guide_md(item)}</li>")
            start_attr = f' start="{start_num}"' if start_num != 1 else ""
            blocks.append(f"<ol{start_attr}>{''.join(ol_li_html)}</ol>")
            continue

        para_lines = [stripped]
        i += 1
        while (
            i < n
            and lines[i].strip()
            and not lines[i].strip().startswith(("#", "|", "- ", "> ", "---", "```"))
            and not re.match(r"^\d+\.\s+", lines[i].strip())
        ):
            para_lines.append(lines[i].strip())
            i += 1
        p_text = " ".join(para_lines)
        p_cls = ' class="meta-line"' if p_text.startswith("**作者") else ""
        blocks.append(f"<p{p_cls}>{_inline_guide_md(p_text)}</p>")

    return "\n".join(blocks)


def build_guide_pdf(md_path: Path = GUIDE_MD_PATH, pdf_path: Path = GUIDE_PDF_PATH) -> Path:
    """Compile 使用说明.md into a styled A4 PDF guide via Playwright Chromium."""
    md_text = md_path.read_text(encoding="utf-8")
    body = _guide_md_to_html_body(md_text)
    full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>QuantumChem AI v0.1.0 使用说明</title>
<style>
@page {{
    size: A4;
    margin: 18mm 16mm 18mm 16mm;
}}
body {{
    font-family: "Microsoft YaHei", "SimSun", "Segoe UI", sans-serif;
    font-size: 9.8pt;
    line-height: 1.56;
    color: #0f172a;
    max-width: 820px;
    margin: 0 auto;
}}
h1.doc-title {{
    font-size: 17pt;
    color: #0f2557;
    text-align: center;
    margin: 2px 0 6px 0;
}}
p.meta-line {{
    text-align: center;
    color: #475569;
    font-size: 9.2pt;
    margin: 0 0 8px 0;
}}
h2 {{
    font-size: 12pt;
    color: #0f2557;
    border-bottom: 1.3pt solid #1e40af;
    padding-bottom: 3px;
    margin-top: 15px;
    margin-bottom: 7px;
    break-after: avoid;
}}
h3 {{
    font-size: 10.4pt;
    color: #1e3a8a;
    margin-top: 11px;
    margin-bottom: 4px;
    break-after: avoid;
}}
hr {{
    border: none;
    border-top: 0.7pt solid #cbd5e1;
    margin: 8px 0;
}}
p {{
    margin: 4px 0 6px 0;
    text-align: justify;
}}
code {{
    font-family: "Consolas", "Courier New", monospace;
    font-size: 8.6pt;
    background: #f1f5f9;
    border: 0.5pt solid #cbd5e1;
    padding: 0 3px;
    border-radius: 3px;
    color: #0f172a;
}}
pre {{
    background: #f8fafc;
    border: 0.7pt solid #cbd5e1;
    border-left: 3pt solid #1e40af;
    border-radius: 4px;
    padding: 7px 10px;
    margin: 6px 0 8px 0;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 8.4pt;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
    break-inside: avoid;
}}
pre code {{
    background: transparent;
    border: none;
    padding: 0;
}}
blockquote.callout {{
    background: #eff6ff;
    border-left: 3pt solid #1d4ed8;
    border-radius: 4px;
    margin: 6px 0 9px 0;
    padding: 6px 10px;
    font-size: 9.1pt;
    color: #1e293b;
    break-inside: avoid;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    margin: 6px 0 10px 0;
    font-size: 8.4pt;
    line-height: 1.42;
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
    border-top: 1.3pt solid #0f2557;
    border-bottom: 0.9pt solid #0f2557;
    padding: 4.5px 6px;
    text-align: left;
    font-weight: 700;
}}
td {{
    border-bottom: 0.5pt solid #cbd5e1;
    padding: 4px 6px;
    vertical-align: top;
}}
td:first-child {{
    min-width: 92px;
    max-width: 215px;
}}
tbody tr:last-child td {{
    border-bottom: 1.3pt solid #0f2557;
}}
ul, ol {{
    margin: 4px 0 8px 0;
    padding-left: 20px;
}}
li {{
    margin-bottom: 4px;
}}
a {{
    color: #1d4ed8;
    text-decoration: none;
}}
</style>
</head>
<body>
{body}
</body>
</html>
"""
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".html", delete=False
    ) as tmp_html:
        tmp_html.write(full_html)
        tmp_uri = Path(tmp_html.name).as_uri()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(tmp_uri, wait_until="networkidle")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                display_header_footer=True,
                header_template=(
                    '<div style="font-family:Microsoft YaHei,sans-serif;font-size:7.6pt;'
                    'color:#64748b;width:100%;text-align:center;">'
                    "QuantumChem AI v0.1.0 使用说明 · 钱昌天（首都师范大学物理系，北京 100048）"
                    "</div>"
                ),
                footer_template=(
                    '<div style="font-family:Microsoft YaHei,sans-serif;font-size:7.6pt;'
                    'color:#64748b;width:100%;text-align:center;">'
                    '第 <span class="pageNumber"></span> / <span class="totalPages"></span> 页'
                    "</div>"
                ),
                margin={"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"},
            )
            browser.close()
    finally:
        Path(tmp_uri.removeprefix("file:///")).unlink(missing_ok=True)
    return pdf_path


def _find_uv() -> str:
    found = shutil.which("uv")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "uv.exe"
    if candidate.exists():
        return str(candidate)
    raise FileNotFoundError("Could not locate `uv` executable to build wheel.")


def build_wheel() -> Path:
    """Build fresh wheel package into dist/ using `uv build --wheel`."""
    uv_exe = _find_uv()
    subprocess.run([uv_exe, "build", "--wheel"], cwd=str(REPO_ROOT), check=True)
    wheels = sorted(DIST_DIR.glob("quantumchem_ai-*.whl"))
    if not wheels:
        raise FileNotFoundError(f"No built wheel found under {DIST_DIR}")
    return wheels[-1]


def _is_forbidden_path(rel: Path) -> bool:
    parts = set(rel.parts)
    if parts & FORBIDDEN_DIR_PARTS:
        return True
    name_low = rel.name.lower()
    if name_low == ".env" or name_low.endswith(".env"):
        return True
    if name_low.startswith("id_rsa"):
        return True
    if rel.as_posix() == "config/settings.toml":
        return True
    return rel.suffix.lower() in FORBIDDEN_SUFFIXES


def _collect_release_entries(wheel_path: Path) -> list[tuple[Path, str]]:
    entries: list[tuple[Path, str]] = []
    seen_arc: set[str] = set()

    def _add(src: Path, arc_rel: str) -> None:
        if not src.exists():
            raise FileNotFoundError(f"Missing required release file: {src}")
        if arc_rel in seen_arc:
            return
        seen_arc.add(arc_rel)
        entries.append((src, f"{RELEASE_ROOT_NAME}/{arc_rel}"))

    for fname in TOP_LEVEL_FILES:
        _add(REPO_ROOT / fname, fname)

    _add(GUIDE_PDF_PATH, "使用说明.pdf")
    _add(REPO_ROOT / "config" / "settings.example.toml", "config/settings.example.toml")
    _add(wheel_path, f"wheel/{wheel_path.name}")

    for rel_dir in INCLUDED_DIRS:
        base = REPO_ROOT / rel_dir
        if not base.exists():
            raise FileNotFoundError(f"Missing required directory: {base}")
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(REPO_ROOT)
            if _is_forbidden_path(rel):
                continue
            _add(p, rel.as_posix())

    for pf in PAPER_FILES:
        _add(REPO_ROOT / pf, pf)

    fig_dir = REPO_ROOT / "paper" / "figures"
    for p in sorted(fig_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(REPO_ROOT)
        if _is_forbidden_path(rel):
            continue
        _add(p, rel.as_posix())

    return entries


def verify_release_zip(zip_path: Path) -> tuple[int, int, int]:
    """Verify ZIP integrity and guarantee zero credentials, DBs, or temp files leaked."""
    total_uncompressed = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        bad = zf.testzip()
        if bad is not None:
            raise AssertionError(f"Corrupted ZIP member: {bad}")
        infos = zf.infolist()
        for info in infos:
            total_uncompressed += info.file_size
            arc = info.filename
            arc_low = arc.lower()
            if arc_low.endswith("/settings.toml") or arc_low == "settings.toml":
                raise AssertionError(f"Forbidden real settings file in ZIP: {arc}")
            if any(part in arc.split("/") for part in FORBIDDEN_DIR_PARTS):
                raise AssertionError(f"Forbidden directory in ZIP: {arc}")
            if any(arc_low.endswith(sfx) for sfx in FORBIDDEN_SUFFIXES):
                raise AssertionError(f"Forbidden file extension in ZIP: {arc}")
            if Path(arc_low).name == ".env" or Path(arc_low).name.startswith("id_rsa"):
                raise AssertionError(f"Forbidden secret filename in ZIP: {arc}")

            if not info.is_dir() and info.file_size <= 512 * 1024:
                raw = zf.read(info.filename)
                if b"\x00" not in raw:
                    txt = raw.decode("utf-8", errors="ignore")
                    if m := re.search(r"sk-[A-Za-z0-9_-]{16,}", txt):
                        raise AssertionError(f"Potential API key leaked in {arc}: {m.group(0)}")
                    if re.search(r"BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY", txt):
                        raise AssertionError(f"Private key block leaked in {arc}")
    return len(infos), total_uncompressed, zip_path.stat().st_size


def build_release_zip() -> Path:
    """Create guide PDF, fresh wheel, and sanitized release ZIP archive."""
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    build_guide_pdf()
    wheel_path = build_wheel()
    entries = _collect_release_entries(wheel_path)

    with zipfile.ZipFile(
        RELEASE_ZIP_PATH,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as zf:
        for src, arcname in entries:
            zf.write(src, arcname=arcname)

    count, raw_bytes, zip_bytes = verify_release_zip(RELEASE_ZIP_PATH)
    print(f"Built guide PDF : {GUIDE_PDF_PATH} ({GUIDE_PDF_PATH.stat().st_size} B)")
    print(f"Built wheel     : {wheel_path} ({wheel_path.stat().st_size} B)")
    print(
        f"Built clean ZIP : {RELEASE_ZIP_PATH} "
        f"({count} files, {raw_bytes:,} B raw -> {zip_bytes:,} B compressed)"
    )
    return RELEASE_ZIP_PATH


if __name__ == "__main__":
    build_release_zip()
