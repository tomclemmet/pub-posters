#!/usr/bin/env python3
"""Combine every poster in output/*.html into a single print-ready PDF.

Usage:
    python combine_pdfs.py

Run this after build.py, once you're happy with everything in output/ -
including any manual edits you've made to fill in blank fields or otherwise
tweak the generated HTML. It prints each output/*.html to its own PDF via
headless Chromium (so the layout matches exactly what you'd get from the
browser's own print dialog, autofit text included), in filename order, then
merges them into output/combined.pdf. The per-poster PDFs are deleted once
merged in - only combined.pdf and the source HTML files are left behind.

Needs the 'playwright' and 'pypdf' packages, and a one-time
`playwright install chromium` after installing requirements.
"""
from pathlib import Path

ROOT = Path(__file__).parent
OUTPUT_DIR = ROOT / "output"


def combine_pdfs() -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "combine_pdfs.py needs the 'playwright' package: pip install -r requirements.txt, "
            "then run 'playwright install chromium' once (downloads a bundled browser)."
        )
    try:
        from pypdf import PdfWriter
    except ImportError:
        raise SystemExit("combine_pdfs.py needs the 'pypdf' package: pip install -r requirements.txt")

    html_paths = sorted(OUTPUT_DIR.glob("*.html"))
    if not html_paths:
        raise SystemExit(f"No .html files found in {OUTPUT_DIR}")

    print(f"Rendering {len(html_paths)} poster(s) to PDF...")
    pdf_paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for html_path in html_paths:
            print(f"* {html_path.name}")
            pdf_path = html_path.with_suffix(".pdf")
            page.goto(html_path.resolve().as_uri())
            page.pdf(path=str(pdf_path), print_background=True, prefer_css_page_size=True)
            pdf_paths.append(pdf_path)
        browser.close()

    combined_path = OUTPUT_DIR / "combined.pdf"
    writer = PdfWriter()
    for pdf_path in pdf_paths:
        writer.append(str(pdf_path))
    with open(combined_path, "wb") as f:
        writer.write(f)
    writer.close()

    for pdf_path in pdf_paths:
        pdf_path.unlink()

    return combined_path


def main():
    combined = combine_pdfs()
    print(f"[ok] combined PDF -> {combined.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
