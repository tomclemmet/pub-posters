#!/usr/bin/env python3
"""Generate print-ready A4-landscape publication posters from a DOI.

Usage:
    python build.py 10.1007/s40273-017-0518-0 [10.xxxx/yyyy ...]
    python build.py                              # prompts for DOIs interactively
    python build.py -f dois.txt                  # bulk build, one DOI per line

Looks each DOI up on PubMed and fills in journal, title, authors, abstract
and citation automatically, generates a QR code, and writes a poster to
output/ - no data file to create or edit. Anything PubMed can't find (most
often because the paper isn't indexed there at all) is just left blank in
the generated HTML - open that file and type the missing text directly into
the relevant tag. Note: rebuilding the same DOI again overwrites the file,
including any manual edits - only rerun a DOI if you want to regenerate it
from scratch.

Once you're happy with everything in output/ (including any manual edits),
run combine_pdfs.py to print it all to one PDF ready for the printer.
"""
import argparse
import base64
import html
import io
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import qrcode
import requests
from jinja2 import Environment, FileSystemLoader
from titlecase import titlecase

ROOT = Path(__file__).parent
COVER_DIR = ROOT / "covers"
OUTPUT_DIR = ROOT / "output"
TEMPLATE_DIR = ROOT / "template"
BOLD_AUTHORS_FILE = ROOT / "mche-authors.txt"
JOURNAL_NAMES_FILE = ROOT / "journal-names.txt"

PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
DOI_URL_RE = re.compile(r"^(?:https?://)?(?:dx\.)?doi\.org/(10\.\S+)$", re.I)


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def normalize_doi_arg(arg: str) -> str:
    """Return a bare DOI from `arg` (bare, or as a doi.org URL)."""
    text = arg.strip()
    m = DOI_URL_RE.match(text)
    if m:
        return m.group(1)
    return text


COVER_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
# How many levels of output/<subfolder>/ nesting cover-image paths tolerate;
# see the comment above cover_candidates in build_from_doi.
COVER_PATH_MAX_DEPTH = 3


def find_cover_image(journal: str):
    slug = slugify(journal)
    for ext in COVER_EXTENSIONS:
        candidate = COVER_DIR / f"{slug}{ext}"
        if candidate.exists():
            return candidate
    return None


def format_initials(initials: str) -> str:
    return " ".join(f"{ch}." for ch in initials)


def load_bold_authors() -> set:
    """Read 'F Last' entries (first initial, then last name) from
    mche-authors.txt, if it exists, e.g. a line reading "C Vass".

    Blank lines and lines starting with '#' are ignored. Matching against
    authors is case-insensitive on first initial + last name, so a missing
    vs. present middle name never affects the match.
    """
    if not BOLD_AUTHORS_FILE.exists():
        return set()
    entries = set()
    for line in BOLD_AUTHORS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        initial, last = parts
        entries.add((initial.strip().lower()[:1], last.strip().lower()))
    return entries


def load_journal_overrides() -> dict:
    """Read 'PubMed name -> Display name' rules from journal-names.txt, if
    it exists, e.g. a line reading:
        Value in health : the journal of the International Society for
        Pharmacoeconomics and Outcomes Research -> Value in Health

    Blank lines and lines starting with '#' are ignored. Matching against
    PubMed's journal field is case-insensitive and ignores extra whitespace.
    """
    if not JOURNAL_NAMES_FILE.exists():
        return {}
    overrides = {}
    for line in JOURNAL_NAMES_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "->" not in line:
            continue
        raw, _, replacement = line.partition("->")
        key = re.sub(r"\s+", " ", raw).strip().lower()
        replacement = replacement.strip()
        if key and replacement:
            overrides[key] = replacement
    return overrides


def normalize_journal_name(raw: str, journal_overrides: dict) -> str:
    """Clean up a journal name as fetched from PubMed: use a matching entry
    from journal-names.txt verbatim if there is one, otherwise title-case it
    (PubMed journal names often come back all-lowercase, or with an unwanted
    subtitle)."""
    key = re.sub(r"\s+", " ", raw).strip().lower()
    if key in journal_overrides:
        return journal_overrides[key]
    return titlecase(raw)


def _elem_text(el) -> str:
    """Full text of an element, including any nested tags PubMed uses for
    inline formatting (e.g. <i>RPGR</i> in a gene name). Plain `.text` or
    `findtext()` silently stop at the first such child, dropping everything
    after it (which lives in that child's `.tail`) - truncating mid-sentence
    whenever an abstract or title contains italicised gene/species names."""
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _extract_fields(article, doi: str, journal_overrides: dict) -> dict:
    """Build the lookup-result dict (see pubmed_lookup_batch) from a single
    <Article> element and the DOI it belongs to."""
    # A "structured abstract" (Objectives/Methods/Results/Conclusions, etc.)
    # comes back from PubMed as several <AbstractText> elements, each with
    # its heading only in a Label attribute - not in the text itself - so
    # joining just the text (as before) silently drops the headings and
    # runs every section together. Re-attach each heading inline (title
    # case, colon, no line break) wherever PubMed provided one; a plain
    # (unlabelled) abstract is unaffected since there's nothing to prefix.
    # "UNLABELLED" is PubMed's own sentinel for "no real heading" (used when
    # the source abstract already writes its headings inline, e.g. as bold
    # text within the one AbstractText) - treat it the same as no label at
    # all rather than printing the literal word "Unlabelled:".
    #
    # A "HIGHLIGHTS" section is a separate bullet-point summary some
    # journals tack on after the real abstract, and "FINANCIAL DISCLOSURE(S)"
    # is a boilerplate funding/COI note - neither is abstract content, so
    # both are dropped entirely rather than rendered as a labelled section.
    DROPPED_ABSTRACT_LABELS = {"HIGHLIGHTS", "FINANCIAL DISCLOSURE", "FINANCIAL DISCLOSURES"}
    abstract_parts = []
    for el in article.findall(".//AbstractText"):
        if (el.get("Label") or "").strip().upper() in DROPPED_ABSTRACT_LABELS:
            continue
        text = _elem_text(el)
        if not text:
            continue
        label = el.get("Label")
        if label and label.strip().upper() == "UNLABELLED":
            label = None
        abstract_parts.append(f"{label.title()}: {text}" if label else text)
    abstract = " ".join(abstract_parts)

    article_title = _elem_text(article.find(".//ArticleTitle"))
    if article_title:
        # PubMed titles are a mix of Title Case and sentence case; titlecase()
        # normalizes to Title Case while leaving already-uppercase acronyms
        # (HIV, COPD, QALY, ...) alone.
        article_title = titlecase(article_title)
    journal_title = _elem_text(article.find(".//Journal/Title"))
    if journal_title:
        journal_title = normalize_journal_name(journal_title, journal_overrides)
    year = (
        article.findtext(".//JournalIssue/PubDate/Year", default="")
        or article.findtext(".//JournalIssue/PubDate/MedlineDate", default="")[:4]
    )
    volume = article.findtext(".//JournalIssue/Volume", default="")
    issue = article.findtext(".//JournalIssue/Issue", default="")
    pages = article.findtext(".//Pagination/MedlinePgn", default="")

    citation_authors = []
    header_authors = []  # list of (display_name, last_name, first_initial) tuples
    for author in article.findall(".//AuthorList/Author"):
        last = author.findtext("LastName")
        initials = author.findtext("Initials")
        forename = author.findtext("ForeName")
        if last and initials:
            citation_authors.append(f"{last}, {format_initials(initials)}")
        elif last:
            citation_authors.append(last)
        first_initial = (forename[:1] if forename else (initials[:1] if initials else "")).lower()
        if last and forename:
            header_authors.append((f"{forename} {last}", last, first_initial))
        elif last:
            header_authors.append((last, last, first_initial))

    result = {}
    if journal_title:
        result["journal"] = journal_title
    if article_title:
        result["title"] = article_title.rstrip(".")
    if abstract:
        result["abstract"] = abstract
    if header_authors:
        result["authors"] = header_authors
    if citation_authors:
        result["_first_author_last"] = citation_authors[0].split(",")[0]
    if year:
        result["_year"] = year

    if citation_authors and journal_title:
        author_str = (
            citation_authors[0]
            if len(citation_authors) == 1
            else ", ".join(citation_authors[:-1]) + ", & " + citation_authors[-1]
        )
        vol_issue = volume
        if issue:
            vol_issue = f"{vol_issue}({issue})" if vol_issue else f"({issue})"
        citation = f"{author_str} ({year})." if year else f"{author_str}."
        if article_title:
            title_text = article_title.rstrip(".")
            citation += f" {title_text}."
        citation += f" {journal_title}"
        if vol_issue:
            citation += f", {vol_issue}"
        if pages:
            citation += f", {pages}"
        citation += f". https://doi.org/{doi}"
        result["citation"] = citation

    return result


def _index_articles_by_doi(xml_content: bytes) -> dict:
    """Parse an efetch XML response (one or more PubmedArticle records) into
    {doi_lowercased: <Article element>}."""
    root = ET.fromstring(xml_content)
    index = {}
    for wrapper in root.findall(".//PubmedArticle"):
        article = wrapper.find(".//Article")
        if article is None:
            continue
        aid = wrapper.find(".//ArticleIdList/ArticleId[@IdType='doi']")
        if aid is None or not (aid.text or "").strip():
            continue
        index[aid.text.strip().lower()] = article
    return index


def pubmed_lookup_batch(dois: list, journal_overrides: dict = None) -> dict:
    """Best-effort lookup of publication details for several DOIs at once,
    using a single esearch + single efetch call (an OR'd search term and a
    comma-separated ID list) rather than one round-trip pair per DOI - this
    keeps bulk builds well under PubMed's rate limit.

    Returns {doi: result_dict} for whichever of the given DOIs PubMed found;
    a DOI not indexed in PubMed (or if the whole lookup fails) is simply
    absent from the returned dict, so callers should fall back to manual
    entry for anything missing.
    """
    journal_overrides = journal_overrides or {}
    if not dois:
        return {}
    try:
        term = " OR ".join(f"{d}[AID]" for d in dois)
        resp = requests.get(
            PUBMED_ESEARCH,
            params={"db": "pubmed", "term": term, "retmode": "json", "retmax": len(dois)},
            timeout=15,
        )
        resp.raise_for_status()
        ids = resp.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return {}

        resp = requests.get(
            PUBMED_EFETCH,
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml"},
            timeout=15,
        )
        resp.raise_for_status()
        by_doi = _index_articles_by_doi(resp.content)
    except (requests.RequestException, ET.ParseError, ValueError):
        return {}

    results = {}
    for doi in dois:
        article = by_doi.get(doi.strip().lower())
        if article is not None:
            try:
                results[doi] = _extract_fields(article, doi, journal_overrides)
            except ValueError:
                pass
    return results


def pubmed_lookup(doi: str, journal_overrides: dict = None) -> dict:
    """Best-effort lookup of publication details from PubMed via DOI. See
    pubmed_lookup_batch for the shape of the returned dict; returns {} if
    the DOI isn't indexed in PubMed or the lookup fails for any reason."""
    return pubmed_lookup_batch([doi], journal_overrides).get(doi, {})


def make_qr_base64(doi: str) -> str:
    img = qrcode.make(f"https://doi.org/{doi}")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def make_doi_slug(doi: str, looked_up: dict) -> str:
    last = looked_up.get("_first_author_last", "")
    year = looked_up.get("_year", "")
    title = looked_up.get("title", "")
    if last and year:
        base = f"{slugify(last)}-{year}"
        if title:
            short_title = "-".join(slugify(title).split("-")[:6])
            if short_title:
                base = f"{base}-{short_title}"
        return base[:80]
    return slugify(doi) or "publication"


def render_authors(authors_list, bold_authors: set) -> str:
    parts = []
    for name, last, first_initial in authors_list:
        escaped = html.escape(name)
        key = (first_initial.strip().lower()[:1], last.strip().lower())
        if key in bold_authors:
            escaped = f"<strong>{escaped}</strong>"
        parts.append(escaped)
    return " • ".join(parts)


def build_from_doi(
    doi: str, env: Environment, css: str, bold_authors: set,
    journal_overrides: dict = None, looked_up: dict = None, out_dir: Path = OUTPUT_DIR,
):
    print(f"* {doi}")
    if looked_up is None:
        looked_up = pubmed_lookup(doi, journal_overrides)
    if looked_up:
        print("  [-] found PubMed match")
    out_stem = make_doi_slug(doi, looked_up)
    edit_hint = f"{out_dir.relative_to(ROOT).as_posix()}/{out_stem}.html"

    journal_raw = looked_up.get("journal", "")  # already normalized, see normalize_journal_name
    title_raw = looked_up.get("title", "")
    authors_list = looked_up.get("authors", [])
    abstract_raw = looked_up.get("abstract", "")
    citation_raw = looked_up.get("citation", "")

    journal_missing = not journal_raw
    title_missing = not title_raw
    authors_missing = not authors_list
    abstract_missing = not abstract_raw
    citation_missing = not citation_raw

    # Cover-image lookup needs the journal name. The HTML always references
    # every possible extension and picks whichever loads (see the
    # cover-loading script in poster.html.j2) rather than baking in
    # "found"/"missing" at build time - so dropping the right file into
    # covers/ later works on the next reload, no rebuild needed. If the
    # journal name itself wasn't found there's no slug to guess from, so
    # this is left for manual editing (see README).
    #
    # Candidates are generated for a few "../" depths, not just one, because
    # a poster built straight into output/ may later be moved into an
    # output/<subfolder>/ (e.g. to keep it out of a combine_pdfs.py batch) -
    # the shallowest depth is tried first so the common case (poster still
    # directly in output/) needs no fallback at all.
    cover_path = None if journal_missing else find_cover_image(journal_raw)
    cover_slug = slugify(journal_raw) if not journal_missing else ""
    cover_candidates = (
        [] if journal_missing
        else [
            f"{'../' * (depth + 1)}covers/{cover_slug}{ext}"
            for depth in range(COVER_PATH_MAX_DEPTH)
            for ext in COVER_EXTENSIONS
        ]
    )

    # Anything PubMed didn't find is simply left blank - no bracketed
    # placeholder text or "missing" styling to edit around, just click in
    # and type. See README for what to fill in for each blank field.
    journal = html.escape(journal_raw)
    title = html.escape(title_raw)
    authors = render_authors(authors_list, bold_authors)
    abstract = html.escape(abstract_raw)
    citation = html.escape(citation_raw)

    template = env.get_template("poster.html.j2")
    page_html = template.render(
        journal=journal,
        title=title,
        authors=authors,
        abstract=abstract,
        citation=citation,
        cover_candidates=json.dumps(cover_candidates),
        qr_base64=make_qr_base64(doi),
        css=css,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{out_stem}.html"
    out_path.write_text(page_html, encoding="utf-8")
    print(f"  [ok] -> {out_path.relative_to(ROOT)}")
    if journal_missing:
        print(f"    (journal not found automatically - edit {edit_hint} directly)")
    elif not cover_path:
        print(f"    (no cover image found - add covers/{cover_slug}.jpg/.png/.webp)")
    if title_missing:
        print(f"    (title not found automatically - edit {edit_hint} directly)")
    if authors_missing:
        print(f"    (authors not found automatically - edit {edit_hint} directly)")
    if abstract_missing:
        print(f"    (abstract not found automatically - edit {edit_hint} directly)")
    if citation_missing:
        print(f"    (citation not found automatically - edit {edit_hint} directly)")

    return out_path


def read_doi_file(path: Path):
    """Read one DOI per line from a text file. Blank lines and lines starting
    with '#' are ignored."""
    dois = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        dois.append(line)
    return dois


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("dois", nargs="*", help="One or more DOIs to build posters for")
    parser.add_argument(
        "-f", "--file", metavar="PATH",
        help="Text file with one DOI per line (blank lines and '#' comments ignored) to build in bulk",
    )
    parser.add_argument(
        "--subdir", metavar="SUBFOLDER",
        help="Write posters into output/SUBFOLDER/ instead of output/ directly "
             "(created if it doesn't exist yet)",
    )
    args = parser.parse_args()

    out_dir = OUTPUT_DIR / args.subdir if args.subdir else OUTPUT_DIR

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    css = (TEMPLATE_DIR / "poster.css").read_text(encoding="utf-8")
    bold_authors = load_bold_authors()
    if bold_authors:
        print(f"Bolding authors matching {len(bold_authors)} name(s) from {BOLD_AUTHORS_FILE.name}")
    journal_overrides = load_journal_overrides()
    if journal_overrides:
        print(f"Renaming {len(journal_overrides)} journal name(s) from {JOURNAL_NAMES_FILE.name}")

    if args.file:
        path = Path(args.file)
        if not path.exists():
            parser.error(f"file not found: {path}")
        dois = [normalize_doi_arg(raw) for raw in read_doi_file(path)]
        if not dois:
            parser.error(f"no DOIs found in {path}")
        print(f"Building {len(dois)} poster(s) from {path.name}...")
        looked_up_map = pubmed_lookup_batch(dois, journal_overrides)
        for doi in dois:
            build_from_doi(doi, env, css, bold_authors, journal_overrides, looked_up_map.get(doi, {}), out_dir)
    elif args.dois:
        dois = [normalize_doi_arg(arg) for arg in args.dois]
        looked_up_map = pubmed_lookup_batch(dois, journal_overrides)
        for doi in dois:
            build_from_doi(doi, env, css, bold_authors, journal_overrides, looked_up_map.get(doi, {}), out_dir)
    else:
        print("No DOI given on the command line - entering interactive mode.")
        while True:
            try:
                raw = input("DOI (blank to quit): ").strip()
            except EOFError:
                break
            if not raw:
                break
            build_from_doi(normalize_doi_arg(raw), env, css, bold_authors, journal_overrides, out_dir=out_dir)


if __name__ == "__main__":
    main()
