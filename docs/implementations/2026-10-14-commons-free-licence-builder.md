# Commons builder: free licences, a people list and year categories

- **Date:** 2026-10-14
- **Milestone / tracker IDs:** M5 track R (evaluation data); no tracker row changes
- **Status:** tool built and run once; the data it produced is local and unverified
- **Commits:** PR to be recorded when merged

## What changed

`evaluation/build_commons_dataset.py` gained three opt-in options; the defaults are unchanged (public
domain only, the built-in list, direct category files):

- `--licences free`: also accepts CC0 and Creative Commons BY and BY-SA files, still read per file from
  Commons' own metadata. A licence name containing NC or ND is refused.
- `--people "A,B"`: the Commons category names to read.
- `--follow-years`: also reads the person's "by year" and "in <year>" subcategories (the person's own
  only; not their films, signatures, logos or other people), at most 60 categories per person, each
  read once, files de-duplicated by title.

## Why

The owner asked for photographs of well-known living people (Jason Statham, Dwayne Johnson, Jennifer
Lawrence, Jennifer Lopez, Jenna Ortega, Zendaya and others). A web-wide image scrape would mean search
engines' terms and untrusted hosts. Wikimedia Commons states a licence per file, so the same builder
that made the public-domain set can read it: most photographs of living people there are CC BY or CC BY-SA
(from Flickr and event photographers), and most of their photographs sit in "by year" subcategories, not
the top category (a dry run showed 0 to 3 files directly for Jennifer Lawrence, Jenna Ortega and
Zendaya, against 22 to 24 for Jason Statham and Dwayne Johnson).

## Decisions

- **Attribution and share-alike.** CC BY and BY-SA ask for credit and, for BY-SA, the same licence on
  adaptations. A private local evaluation set meets this by keeping author, licence, licence URL and
  source page in the manifest; the files are never committed or redistributed (the folder is
  Git-ignored). Recorded in the licensing file.
- **Labels stay unverified.** The label is the Commons category of the person. A year category can
  hold a photograph of the person with other people, so the label-review tool is the next step.
- **Not a web scrape.** No search engine and no arbitrary site are read.

## Verification

- `uv run pytest tests/unit/test_commons_builder.py -q`: 16 passed (free versus NC/ND and unknown
  licences, the default still public-domain only, which subcategories are followed, a category read once
  with cycles, files not repeated, the direct mode reading no subcategory). ruff and mypy clean.
- The tool was run for 38 people (see the status page); counts are in the local manifest.
- **Not verified:** that every followed category holds only the named person; Commons' licence
  metadata is taken as given.

## Open issues / follow-ups

- Review the labels (`label_review.py --people ...`) before any quality claim; many year categories hold
  group photographs.
