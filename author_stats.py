#!/usr/bin/env python3
"""Report how often each MCHE author appears across output/*.html posters.

Reads the authors line out of every poster in output/ (the <p class="authors">
paragraph written by build.py), matches each author against mche-authors.txt
by first-initial + last-name (same rule build.py uses to decide who gets
bolded), and prints a table of first-author, last-author, and total author
counts per MCHE author.

Usage:
    python author_stats.py
"""
import html
import re
from pathlib import Path

ROOT = Path(__file__).parent
OUTPUT_DIR = ROOT / "output"
BOLD_AUTHORS_FILE = ROOT / "mche-authors.txt"

AUTHORS_P_RE = re.compile(r'<p class="authors">(.*?)</p>', re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")


def load_mche_authors() -> list:
    """Return [(first_initial_lower, last_name_lower, display_line), ...] in file order."""
    authors = []
    for line in BOLD_AUTHORS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        initial, last = parts
        authors.append((initial.strip().lower()[:1], last.strip().lower(), line))
    return authors


def parse_authors(html_path: Path) -> list:
    """Return the list of plain-text author names in order for one poster."""
    text = html_path.read_text(encoding="utf-8")
    match = AUTHORS_P_RE.search(text)
    if not match:
        return []
    names = []
    for chunk in match.group(1).split("•"):
        name = html.unescape(TAG_RE.sub("", chunk)).strip()
        if name:
            names.append(name)
    return names


def match_key(name: str):
    """Return (first_initial, last_name) for a rendered display name, mirroring build.py."""
    tokens = name.split()
    if not tokens:
        return None
    first_initial = tokens[0][:1].lower()
    last_name = tokens[-1].lower()
    return first_initial, last_name


def main():
    mche_authors = load_mche_authors()
    lookup = {(initial, last): line for initial, last, line in mche_authors}
    stats = {line: {"first": 0, "last": 0, "total": 0} for _, _, line in mche_authors}

    html_paths = sorted(OUTPUT_DIR.glob("*.html"))
    if not html_paths:
        raise SystemExit(f"No .html files found in {OUTPUT_DIR}")

    paper_count = 0
    for html_path in html_paths:
        names = parse_authors(html_path)
        if not names:
            continue
        paper_count += 1
        for i, name in enumerate(names):
            key = match_key(name)
            line = lookup.get(key)
            if line is None:
                continue
            stats[line]["total"] += 1
            if i == 0:
                stats[line]["first"] += 1
            if i == len(names) - 1 and len(names) > 1:
                stats[line]["last"] += 1

    rows = sorted(stats.items(), key=lambda kv: (-kv[1]["total"], kv[0]))

    name_width = max((len(line) for line, _ in rows), default=6)
    name_width = max(name_width, len("Author"))
    header = f"{'Author':<{name_width}}  {'First':>5}  {'Last':>5}  {'Total':>5}"
    print(f"{paper_count} paper(s) in {OUTPUT_DIR.name}/\n")
    print(header)
    print("-" * len(header))
    for line, counts in rows:
        print(
            f"{line:<{name_width}}  {counts['first']:>5}  {counts['last']:>5}  {counts['total']:>5}"
        )


if __name__ == "__main__":
    main()
