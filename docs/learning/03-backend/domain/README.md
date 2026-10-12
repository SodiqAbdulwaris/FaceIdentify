# Domain: the product's vocabulary

Every name the application uses for the things it remembers, one lesson each, tied to the tables that hold them. Read in
order the first time; each lesson stands alone afterwards.

| Lesson | Teaches |
|---|---|
| [01 Vocabulary](01-vocabulary.md) | the nouns, how they relate, and the three words people mix up |
| [02 Sources and artifacts](02-sources-and-artifacts.md) | an imported picture and the files behind it |
| [03 Observations and representations](03-observations-and-representations.md) | a detected face and its vector |
| [04 Identities and lineage](04-identities-and-lineage.md) | the persistent "who is this, visually", merges and splits |
| [05 People and naming](05-people-and-naming.md) | names, kept apart from identities |
| [06 Occurrences and evidence](06-occurrences-and-evidence.md) | where an identity appears, and why a decision was made |
| [07 States, revisions and provenance](07-states-revisions-provenance.md) | the lifecycle rules that every table shares |

## Look at the real rows (used by every lesson here)

**Works with no models. Verified 2026-10-12.** Build the small practice library from
[start-here 07](../../00-start-here/07-run-it-and-see-it-work.md): import `red.png`, `green.png` and `red-copy.png` (storage
mode `MANAGED`) and process each, on the development profile. Stop the backend, then read the database **read-only** with
this helper (save it as `q.py`; the database is at `<library root>/database/library.db`):

```python
import sqlite3, sys
con = sqlite3.connect("file:" + sys.argv[1] + "/database/library.db?mode=ro", uri=True)
for query in sys.argv[2:]:
    print("==", query)
    for row in con.execute(query):
        print(row)
```

Run it as `uv run python q.py ~/faceidentify-play/lib "select state, count(*) from sources group by 1"`. Every lesson here
uses it. Never open the database in a tool that writes; the lessons only `select`.

The practice library, observed, after processing the three pictures: 3 `sources` (`ACTIVE`), 3 `observations`, 3
`representations` (`ACTIVE`, dimension 64, 256 bytes each), 2 `identities` (`red.png` and `red-copy.png` share one),
3 `occurrences` (`IMAGE`), 3 `evidence` rows (two `IDENTITY_CREATED`, one `IDENTITY_MATCHED`).

Related: [the specs](../../../specs/identity-and-memory-model-v1.md) are the authority; this folder explains them.
Back to [the backend](../README.md).
