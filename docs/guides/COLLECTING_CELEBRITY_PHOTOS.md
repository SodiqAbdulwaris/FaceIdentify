# Collecting celebrity photographs by hand

The Commons download produced pictures that were not usable (clothing, objects, signatures, groups),
so these folders are filled by hand. This guide says where to look, what to keep, and how to number
the files. Nothing here is committed: the pictures are copyrighted works and biometric data, kept on
this machine for evaluation only and never shared.

## The folders

`evaluation/datasets/celebs-manual/` (Git-ignored) holds one folder per person, made by
`uv run python evaluation/prepare_manual_dataset.py init --out evaluation/datasets/celebs-manual`.
The list of people is `people.txt` in that folder: edit it (one name per line) and run `init` again to
add a person; an existing folder is never touched.

## What to collect, per person

- **8 to 15 pictures, at least 6 usable.** Six is the least that gives 5 to enrol and 1 to search with.
- **One person, the face clearly visible and not tiny.** Aim for 400 pixels or more on the short side;
  below 112 is flagged by the numbering script.
- **A real spread:** different years, lighting, expressions, angles, hair, with or without glasses or a
  beard. The point is whether the same person is found across photographs, so near-identical shots from
  one event add little.
- **Avoid:** group photographs, wardrobe or dress close-ups, posters, logos, signatures, album covers,
  film stills with another face as large, heavy filters, drawings and the same picture twice.

## Where to go

1. **Wikimedia Commons (best: every file shows its licence).** Open the person's category below. The
   photographs of living people are often in the *"<name> by year"* subcategories, not the top level.
   Open a picture, then use the **Download** menu and pick a size around 800 to 1,200 pixels wide.
   Prefer files marked *CC BY*, *CC BY-SA* or *CC0*.
2. **The person's Wikipedia page.** Its pictures come from Commons: click one to reach the Commons file
   page and its licence. Good for finding a clear portrait.
3. **Flickr** (search the name, then *Any licence* to *All Creative Commons*). Many event photographers
   publish under CC BY or CC BY-SA.
4. **Official press kits and studio sites** for a recent, clean portrait. Rights are usually not
   open; fine for local evaluation, not for sharing.
5. **Image search** (for example *Tools, Usage rights, Creative Commons licences*). Use it last: results
   are a mix of sources and often include the unusable kinds listed above.

Pictures from a source with a licence are easier to defend later; whichever you use, keep them local.

## Starting points

"Seen" is the number of JPEG photographs the 2026-10-14 dry run found directly in the top Commons
category (0 usually means the pictures are in subcategories).

| Person | Folder | Commons category | Seen | Notes |
|---|---|---|---|---|
| Jason Statham | `Jason_Statham` | [Commons](https://commons.wikimedia.org/wiki/Category:Jason_Statham) | 24 | Top category has plenty. |
| Dwayne Johnson | `Dwayne_Johnson` | [Commons](https://commons.wikimedia.org/wiki/Category:Dwayne_Johnson) | 22 | Top category has plenty. |
| Jennifer Lawrence | `Jennifer_Lawrence` | [Commons](https://commons.wikimedia.org/wiki/Category:Jennifer_Lawrence) | 0 | Open 'Jennifer Lawrence by year'; skip 'Katniss Everdeen' and 'Signatures'. |
| Jennifer Lopez | `Jennifer_Lopez` | [Commons](https://commons.wikimedia.org/wiki/Category:Jennifer_Lopez) | 2 | Open 'by year'; skip 'Green Versace dress', 'logos', 'star', 'Signatures'. |
| Jenna Ortega | `Jenna_Ortega` | [Commons](https://commons.wikimedia.org/wiki/Category:Jenna_Ortega) | 0 | Open 'Jenna Ortega by year'. |
| Zendaya | `Zendaya` | [Commons](https://commons.wikimedia.org/wiki/Category:Zendaya) | 0 | Open 'Zendaya by year'; skip 'by clothing', 'wearing lipstick', 'album covers', 'Signatures'. |
| Tom Hanks | `Tom_Hanks` | [Commons](https://commons.wikimedia.org/wiki/Category:Tom_Hanks) | 20 |  |
| Vin Diesel | `Vin_Diesel` | [Commons](https://commons.wikimedia.org/wiki/Category:Vin_Diesel) | 27 |  |
| Kevin Hart | `Kevin_Hart` | [Commons](https://commons.wikimedia.org/wiki/Category:Kevin_Hart) | 27 |  |
| Mark Wahlberg | `Mark_Wahlberg` | [Commons](https://commons.wikimedia.org/wiki/Category:Mark_Wahlberg) | 12 |  |
| Morgan Freeman | `Morgan_Freeman` | [Commons](https://commons.wikimedia.org/wiki/Category:Morgan_Freeman) | 11 |  |
| Leonardo DiCaprio | `Leonardo_DiCaprio` | [Commons](https://commons.wikimedia.org/wiki/Category:Leonardo_DiCaprio) | 11 |  |
| Idris Elba | `Idris_Elba` | [Commons](https://commons.wikimedia.org/wiki/Category:Idris_Elba) | 13 |  |
| Will Smith | `Will_Smith` | [Commons](https://commons.wikimedia.org/wiki/Category:Will_Smith) | 7 | Also its subcategories. |
| Lady Gaga | `Lady_Gaga` | [Commons](https://commons.wikimedia.org/wiki/Category:Lady_Gaga) | 11 | Many costumes: choose clear face shots. |
| Selena Gomez | `Selena_Gomez` | [Commons](https://commons.wikimedia.org/wiki/Category:Selena_Gomez) | 8 |  |
| Brad Pitt | `Brad_Pitt` | [Commons](https://commons.wikimedia.org/wiki/Category:Brad_Pitt) | 7 |  |
| Keanu Reeves | `Keanu_Reeves` | [Commons](https://commons.wikimedia.org/wiki/Category:Keanu_Reeves) | 5 |  |
| Natalie Portman | `Natalie_Portman` | [Commons](https://commons.wikimedia.org/wiki/Category:Natalie_Portman) | 5 |  |
| Emma Stone | `Emma_Stone` | [Commons](https://commons.wikimedia.org/wiki/Category:Emma_Stone) | 5 |  |
| Angelina Jolie | `Angelina_Jolie` | [Commons](https://commons.wikimedia.org/wiki/Category:Angelina_Jolie) | 6 |  |
| Tom Cruise | `Tom_Cruise` | [Commons](https://commons.wikimedia.org/wiki/Category:Tom_Cruise) | 5 |  |
| Taylor Swift | `Taylor_Swift` | [Commons](https://commons.wikimedia.org/wiki/Category:Taylor_Swift) | 4 | Open 'by year'. |
| Scarlett Johansson | `Scarlett_Johansson` | [Commons](https://commons.wikimedia.org/wiki/Category:Scarlett_Johansson) | 0 | Open its subcategories (7). |
| Margot Robbie | `Margot_Robbie` | [Commons](https://commons.wikimedia.org/wiki/Category:Margot_Robbie) | 2 | Open its subcategories (12). |
| Emma Watson | `Emma_Watson` | [Commons](https://commons.wikimedia.org/wiki/Category:Emma_Watson) | 1 | Open its subcategories (6). |
| Rihanna | `Rihanna` | [Commons](https://commons.wikimedia.org/wiki/Category:Rihanna) | 1 | Open its subcategories (7). |
| Beyoncé | `Beyonce` | [Commons](https://commons.wikimedia.org/wiki/Category:Beyonc%C3%A9) | 0 | The category may be named differently; search Commons for 'Beyoncé'. |
| Ariana Grande | `Ariana_Grande` | [Commons](https://commons.wikimedia.org/wiki/Category:Ariana_Grande) | 0 | Open its subcategories (4). |
| Chris Hemsworth | `Chris_Hemsworth` | [Commons](https://commons.wikimedia.org/wiki/Category:Chris_Hemsworth) | 0 | Open its subcategories (3). |
| Henry Cavill | `Henry_Cavill` | [Commons](https://commons.wikimedia.org/wiki/Category:Henry_Cavill) | 0 | Few free photos; try Flickr. |
| Ryan Reynolds | `Ryan_Reynolds` | [Commons](https://commons.wikimedia.org/wiki/Category:Ryan_Reynolds) | 1 | Open its subcategories (3). |
| Zoe Saldaña | `Zoe_Saldana` | [Commons](https://commons.wikimedia.org/wiki/Category:Zoe_Salda%C3%B1a) | 3 |  |
| Gal Gadot | `Gal_Gadot` | [Commons](https://commons.wikimedia.org/wiki/Category:Gal_Gadot) | 1 |  |
| Anne Hathaway | `Anne_Hathaway` | [Commons](https://commons.wikimedia.org/wiki/Category:Anne_Hathaway) | 0 | No category found by the dry run; search Commons. |
| Robert Downey Jr. | `Robert_Downey_Jr` | [Commons](https://commons.wikimedia.org/wiki/Category:Robert_Downey_Jr.) | 0 | No category found by the dry run; search Commons. |
| Chris Evans | `Chris_Evans` | [Commons](https://commons.wikimedia.org/wiki/Category:Chris_Evans) | 0 | No category found by the dry run (several people share the name); search Commons for 'Chris Evans (actor)'. |
| Michael B. Jordan | `Michael_B_Jordan` | [Commons](https://commons.wikimedia.org/wiki/Category:Michael_B._Jordan) | 0 | Open its subcategories (3). |

## After saving pictures

```bash
# see what would happen (nothing changes)
uv run python evaluation/prepare_manual_dataset.py number --out evaluation/datasets/celebs-manual
# do it: files become 001.jpg, 002.jpg, ... inside each person's folder
uv run python evaluation/prepare_manual_dataset.py number --out evaluation/datasets/celebs-manual --apply
```

What the script does:
- gives each new picture the next number (existing numbers never change, so review decisions stay valid);
- keeps JPEGs as they are and converts PNG, WebP and BMP to JPEG;
- moves anything unreadable, an AVIF (convert it to JPG first), or a duplicate into `_skipped/` inside
  that person's folder, and puts your original files in `_originals/`; nothing is ever deleted or
  overwritten; a picture saved under two people is kept once;
- records the original name and hashes in `rename-log.jsonl` and writes `manifest.json` and
  `PROVENANCE.json`, which the review and evaluation scripts read.

Then review the labels before using the set:

```bash
PYTHONPATH=. uv run python evaluation/label_review.py serve --dataset evaluation/datasets/celebs-manual --reviewer <your name>
```

The folder name is only your label; a wrong picture in the wrong folder is the main way this set can
mislead, so the review matters.
