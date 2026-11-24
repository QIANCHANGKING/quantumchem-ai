"""Spike 10: Verify Jinja2 -> HTML -> Playwright Chromium PDF with Chinese fonts and SVG."""

from pathlib import Path

from jinja2 import Template
from playwright.sync_api import sync_playwright

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<style>
  @page { size: A4; margin: 20mm 16mm; }
  body {
    font-family: "Microsoft YaHei", "SimSun", "Noto Sans CJK SC", sans-serif;
    font-size: 11pt;
    color: #222;
  }
  h1 { color: #1b365d; border-bottom: 2px solid #1b365d; padding-bottom: 4px; }
  .svg-box { margin: 16px 0; text-align: center; }
</style>
</head>
<body>
  <h1>{{ title }}</h1>
  <p>体系：<strong>{{ cluster }}</strong>；基态多重度：{{ mult }}；结合能：{{ eb }} eV/atom。</p>
  <div class="svg-box">
    {{ inline_svg }}
  </div>
  <div class="svg-box">
    <img src="{{ svg_uri }}" width="260" alt="SVG file" />
  </div>
</body>
</html>
"""

SAMPLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="260" height="120" viewBox="0 0 260 120">
  <rect x="2" y="2" width="256" height="116" fill="#f7f9fc" stroke="#1b365d" stroke-width="2"/>
  <line x1="40" y1="80" x2="110" y2="80" stroke="#d62728" stroke-width="3"/>
  <line x1="150" y1="40" x2="220" y2="40" stroke="#1f77b4" stroke-width="3" stroke-dasharray="6,3"/>
  <text x="75" y="100" text-anchor="middle" font-size="12" fill="#333">HOMO (中文标注)</text>
  <text x="185" y="28" text-anchor="middle" font-size="12" fill="#333">LUMO</text>
</svg>"""


def main() -> None:
    out_dir = Path(__file__).parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    svg_path = out_dir / "levels.svg"
    html_path = out_dir / "report.html"
    pdf_path = out_dir / "report.pdf"

    svg_path.write_text(SAMPLE_SVG, encoding="utf-8")
    html = Template(HTML_TEMPLATE).render(
        title="QuantumChem AI 计算报告（P0 PDF 验证）",
        cluster="Al₁₂Ni",
        mult=2,
        eb="2.84",
        inline_svg=SAMPLE_SVG,
        svg_uri=svg_path.resolve().as_uri(),
    )
    html_path.write_text(html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template='<div style="font-size:8px;width:100%;text-align:right;padding-right:16mm;">QuantumChem AI</div>',
            footer_template='<div style="font-size:8px;width:100%;text-align:center;">第 <span class="pageNumber"></span> / <span class="totalPages"></span> 页</div>',
        )
        browser.close()

    assert pdf_path.exists() and pdf_path.stat().st_size > 1000
    print(f"PDF generated: {pdf_path} ({pdf_path.stat().st_size} bytes)")
    print("PASS: spike_10_playwright_pdf")


if __name__ == "__main__":
    main()
