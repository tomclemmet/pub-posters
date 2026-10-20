#!/usr/bin/env python3
"""Combine every poster in output/*.html into a single print-ready PDF.

Usage:
    python combine_pdfs.py
    python combine_pdfs.py some-subfolder   # only output/some-subfolder/*.html

Run this after build.py, once you're happy with everything in output/ -
including any manual edits you've made to fill in blank fields or otherwise
tweak the generated HTML. It prints each output/*.html to its own PDF via
headless Chromium (so the layout matches exactly what you'd get from the
browser's own print dialog, autofit text included), in filename order, then
merges them into a combined PDF. The per-poster PDFs are deleted once merged
in - only the combined PDF and the source HTML files are left behind.

Passing a subfolder name restricts this to output/<subfolder>/*.html and
writes output/combined_<subfolder>.pdf instead of output/combined.pdf -
handy for keeping a batch of posters (e.g. ones you don't want in the main
combined PDF) separate while still landing all combined PDFs in one place.

Needs the 'playwright' and 'pypdf' packages, and a one-time
`playwright install chromium` after installing requirements.
"""
import argparse
from pathlib import Path

ROOT = Path(__file__).parent
OUTPUT_DIR = ROOT / "output"


def combine_pdfs(output_dir: Path = OUTPUT_DIR, combined_path: Path = None) -> Path:
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

    html_paths = sorted(output_dir.glob("*.html"))
    if not html_paths:
        raise SystemExit(f"No .html files found in {output_dir}")

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

    if combined_path is None:
        combined_path = output_dir / "combined.pdf"
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
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "subdir", nargs="?", metavar="SUBFOLDER",
        help="Only combine output/SUBFOLDER/*.html, writing output/combined_SUBFOLDER.pdf "
             "(default: output/ itself, writing output/combined.pdf)",
    )
    args = parser.parse_args()

    if args.subdir:
        output_dir = OUTPUT_DIR / args.subdir
        name_part = args.subdir.strip("/\\").replace("/", "_").replace("\\", "_")
        combined_path = OUTPUT_DIR / f"combined_{name_part}.pdf"
    else:
        output_dir = OUTPUT_DIR
        combined_path = OUTPUT_DIR / "combined.pdf"
    if not output_dir.is_dir():
        parser.error(f"no such directory: {output_dir}")

    combined = combine_pdfs(output_dir, combined_path)
    print(f"[ok] combined PDF -> {combined.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
