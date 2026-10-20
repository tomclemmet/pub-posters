# pub-posters

Generates print-ready A4-landscape publication posters from a DOI. Details come
from PubMed; each poster is an HTML file in `output/`, and they can be combined
into one PDF for printing.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium   # only needed for combine_pdfs.py
```

## Commands

```bash
python build.py 10.xxxx/yyyy [10.xxxx/zzzz ...]   # build posters from DOIs
python build.py                                   # prompt for DOIs
python build.py -f dois.txt                       # one DOI per line (# comments ok)
python build.py --subdir extras ...               # write to output/extras/

python combine_pdfs.py                            # output/*.html -> output/combined.pdf
python combine_pdfs.py extras                     # output/extras/ -> output/combined_extras.pdf

python author_stats.py                            # first/last/total author counts for team members
```

## Workflow

1. Add a cover image per journal to `covers/` (`.jpg`/`.jpeg`/`.png`/`.webp`,
   named after the journal, e.g. `value-in-health.jpg`). It can be added later;
   the poster picks it up on reload.
2. Run `build.py`.
3. Check the HTML in `output/`. Anything PubMed couldn't find is left blank:
   edit the tag directly (`journal`, `paper-title`, `authors`, `abstract`,
   `citation`, `cover`). Rebuilding a DOI overwrites manual edits.
4. Run `combine_pdfs.py`, or open an HTML file and print (A4, landscape,
   background graphics on).

## Config files

- `journal-names.txt`: `PubMed name -> Display name` rules. Journal names are
  title-cased by default; add a rule to fix long names or acronyms (e.g. `PLOS ONE -> PLOS ONE`).
  The result is also used to find the cover image.
- `mche-authors.txt`: `F Lastname` per line. Matching authors are bolded
  (also used by `author_stats.py`).
