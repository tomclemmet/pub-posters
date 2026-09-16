# pub-posters

Generates print-ready A4-landscape publication posters (matching the office
board format), straight from a DOI.

## Setup (one-time)

```bash
pip install -r requirements.txt
```

If you plan to use `combine_pdfs.py` (see below), also run this once to
download the headless browser it uses:

```bash
playwright install chromium
```

## Add a new publication

1. If you already have a cover image for the journal, drop it into `covers/`,
   named after the journal (lowercased, spaces/punctuation → `-`), e.g.
   `covers/somejournal.jpg`. Accepted formats: `.jpg`, `.jpeg`, `.png`,
   `.webp`. One image per *journal* is enough — it's reused for every
   publication in that journal.

   Don't have it yet? Build the poster anyway — the poster HTML checks for
   the cover image every time it's opened, not just at build time, so once
   you drop the file into `covers/` later, just reopen (or reload) the HTML
   and the cover appears — no rebuild needed. Until then it just shows as a
   broken image.

2. Build it, either by passing the DOI directly:

   ```bash
   python build.py 10.xxxx/yyyy
   ```

   or by just running `python build.py` with no arguments — it'll prompt you
   for a DOI (and keep prompting for more; press Enter on a blank line to
   stop):

   ```bash
   python build.py
   # DOI (blank to quit): 10.xxxx/yyyy
   ```

   This looks the DOI up on PubMed, fills in journal, title, authors,
   abstract and citation automatically, generates the QR code, and writes a
   poster straight to `output/` — no data file to create or edit.

3. Open the generated file in `output/` in a browser and print (Ctrl+P → A4,
   landscape, background graphics on).

If PubMed can't find something — which, most often, means the paper isn't
indexed there at all, so *everything* comes back blank rather than just one
field — the poster still builds, just with those fields left empty. Open the
HTML file in a text editor, find the relevant (empty) tag, and type the text
straight in — there's no placeholder text or "missing" styling to work
around, so there's nothing to delete first:

| Field | Tag to edit |
| --- | --- |
| Journal | `<h1 class="journal">` |
| Title | `<h2 class="paper-title">` |
| Authors | `<p class="authors">` |
| Abstract | `<p class="abstract">` |
| Citation | `<footer class="citation">` |
| Cover image | `<img class="cover" ...>` — add a `src="../covers/yourfile.jpg"` attribute (see step 1 above for the naming convention if the file doesn't exist yet) |

Then reopen it in the browser to print. (Rebuilding the same DOI again
overwrites the file, so only rerun a DOI if you want to start over.)

You can pass several DOIs at once:

```bash
python build.py 10.xxxx/yyyy 10.xxxx/zzzz
```

Or build a whole batch from a text file, one DOI per line (blank lines and
`#` comments are ignored):

```bash
python build.py -f dois.txt
```

## Printing a batch as one PDF

Once everything in `output/` looks right — including any manual edits you've
made to fill in blank fields or otherwise tweak the HTML — combine it all
into one PDF ready to send to the printer:

```bash
python combine_pdfs.py
```

This is a separate step from `build.py` on purpose, so you can freely edit
the generated HTML files first without them getting overwritten. It renders
every `output/*.html` to PDF with a real headless browser (Chromium via
Playwright), in filename order, so the layout matches exactly what you'd get
from the browser's own print dialog, autofit text included, then merges them
into `output/combined.pdf`. Needs the one-time `playwright install chromium`
step from Setup above.

Only `combined.pdf` is kept — the individual per-poster PDFs used to build it
are deleted once merged in. The source HTML files are left alone either way.

## Journal names

PubMed's journal name is often inconsistently cased or padded with a long
subtitle (e.g. `value in health : the journal of the international society
for pharmacoeconomics and outcomes research`). Every journal name is
automatically title-cased, and you can add a `PubMed name -> Display name`
rule to `journal-names.txt` to replace it outright instead, e.g.:

```
Value in health : the journal of the International Society for Pharmacoeconomics and Outcomes Research -> Value in Health
```

Matching is case-insensitive and ignores extra whitespace; blank lines and
`#` comments are ignored. This is also the fix for all-caps acronym names
(e.g. "PLOS ONE") that automatic title-casing would otherwise mangle into
"Plos One" — add a rule mapping the name to itself.

The resulting name (renamed or title-cased) is also what's used to look up
the cover image in `covers/`, so tidying up a journal's name here also
tidies up the cover-image filename you need to add.

## Bolding specific authors (e.g. your team)

Add `F Lastname` entries (first initial, then last name), one per line, to
`mche-authors.txt` (blank lines and `#` comments are ignored), e.g.:

```
K Payne
C Vass
```

Any author on a poster whose PubMed first initial + last name matches a line
(case-insensitive) has their whole name bolded — the rest of the byline is
left as-is. Matching only uses the first initial, so a missing vs. present
middle name never causes a mismatch. Two authors who share both a first
initial and last name would still be indistinguishable, but that's much
rarer than a shared surname alone.

## Notes

- The QR code always links to `https://doi.org/{doi}`.
- The output filename is derived from the first author's surname, year, and
  the paper's title.
