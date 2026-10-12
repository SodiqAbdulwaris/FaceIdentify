# The FaceIdentify learning guide

**What this is.** A folder of small, practical lessons that teach you how this codebase works and how
to work in it. You read code you did not type, so every lesson does two things: it explains the
idea in plain words, and it shows you how to **set it up, run it, see it work, change it safely and
check the change**, with commands that were really run.

**Who it is for.** You, the owner. It assumes you can read English and use a computer. It assumes
nothing else: Python, SQL, web pages, Rust and machine learning are all taught from zero, using
real files from this repository.

**Where it came from.** It replaces the single 2,400-line file `docs/research/codebase-learning-guide.md`
(which is now a short index pointing here). Every part of that guide was moved and corrected against
the code; the implementation entry
[`2026-10-12-learning-guide-restructure.md`](../implementations/2026-10-12-learning-guide-restructure.md)
lists where each part went.

## How to use it

1. Pick a **reading path** below that matches what you want to do.
2. Open the folder's `README.md` for a one-line description of each lesson.
3. In each lesson, do the **Try it** section at a computer. Reading alone teaches far less.
4. Finish with the **Exercises**; the answers are at the bottom of the same file.

## Reading paths

| I want to... | Read, in this order |
|---|---|
| Understand what the app is, in an hour | [00-start-here](00-start-here/README.md) lessons 01 to 05, then [one photograph, end to end](07-walkthrough-and-glossary/01-one-photograph.md) |
| Run it on my machine and see it work | [set up your machine](00-start-here/06-set-up-your-machine.md), then [run it and see it work](00-start-here/07-run-it-and-see-it-work.md), then [call the API](03-backend/api/01-call-the-api.md) |
| Read Python (I cannot yet) | [01-basics/python](01-basics/python/README.md) in order, then [read a real function](01-basics/python/07-read-a-real-function.md) |
| Run the tests and the checks | [pytest](01-basics/tools/03-pytest.md), [ruff and mypy](01-basics/tools/04-ruff-and-mypy.md), [CI](01-basics/tools/06-ci.md) |
| Understand how a face becomes a decision | [recognition ideas](01-basics/recognition-ideas/README.md), then [03-backend/recognition](03-backend/recognition/README.md), then [thresholds and errors](01-basics/recognition-ideas/05-thresholds-and-errors.md) |
| Know where my data lives and how it stays safe | [02-data-and-storage](02-data-and-storage/README.md), then [03-backend/lifecycle](03-backend/lifecycle/README.md), then [recovery](03-backend/architecture/06-recovery.md) |
| Add or change an API route | [the API conventions](03-backend/api/README.md), [add a route](03-backend/api/02-add-a-route.md), then the route's own lesson in [routes](03-backend/api/routes/README.md) |
| Add a column to the database | [migrations](02-data-and-storage/04-migrations-alembic.md) (describes it, does not commit one) |
| Change a screen | [04-frontend](04-frontend/README.md), then [add a screen](04-frontend/10-add-a-screen.md) |
| Understand the desktop window | [05-desktop-shell](05-desktop-shell/README.md) |
| Measure recognition quality | [06-evaluation-and-operations](06-evaluation-and-operations/README.md) |
| Contribute or review a pull request | [git and pull requests](01-basics/tools/05-git-and-pull-requests.md), then [rules, branches, reviews](06-evaluation-and-operations/06-rules-branches-reviews.md) |
| Look up a word | [glossary](07-walkthrough-and-glossary/04-glossary.md) |

## The folders

| Folder | What is in it |
|---|---|
| [00-start-here](00-start-here/README.md) | What FaceIdentify is, the four programs, authoritative versus derived data, the layers, one request end to end, setting up your machine, running it |
| [01-basics](01-basics/README.md) | `python/` (the language), `tools/` (uv, pytest, ruff, mypy, git, CI), `recognition-ideas/` (vectors, models, thresholds), `topic-map/` (the old research checklist, answered) |
| [02-data-and-storage](02-data-and-storage/README.md) | SQL, SQLite, transactions, migrations, SQLAlchemy, the vector index, erasure, files, and how to read a database and a log |
| [03-backend](03-backend/README.md) | `architecture/`, `api/` (with one lesson per route module), `domain/`, `processing/`, `recognition/`, `runtime-and-worker/`, `lifecycle/` |
| [04-frontend](04-frontend/README.md) | Web basics, TypeScript, React, the app's structure, queries, events, each screen, styling, tests, adding a screen |
| [05-desktop-shell](05-desktop-shell/README.md) | Rust, Tauri, the sidecar contract, the native dialogs, building and testing the shell |
| [06-evaluation-and-operations](06-evaluation-and-operations/README.md) | The evaluation scripts, how a real-model run works, and the project's rules, branches, reviews and decisions |
| [07-walkthrough-and-glossary](07-walkthrough-and-glossary/README.md) | One photograph end to end, a reading path through the code, exercises, the glossary, further reading |

## What every lesson looks like

1. **What this is and why it exists**: plain language, every term defined.
2. **Where it lives**: exact paths, with the key functions or classes.
3. **How it works**: a short walk through the real code.
4. **Try it**: numbered steps, exact commands, the expected result described in words and how to tell
   it worked.
5. **Change it**: one safe modification, the test to run, and what should break if you get it wrong.
6. **Break it on purpose** (some lessons): a mistake and the error it gives.
7. **Exercises**, with answers at the bottom.
8. **Related files**: links.

## The markers

**What state a thing is in**

- **[built]**: exists in the repository and is tested.
- **[designed]**: written in a specification, not built yet.
- **[researched]**: considered, not chosen or not needed yet.

**Which profile a "Try it" needs**

- **Works with no models**: runs on the *development profile* (a fake catalog and a fake perception
  that stand in for the neural networks) or on the test fixtures. You need nothing but this repository.
- **Needs the local models**: needs the `buffalo_l` model files installed on your machine. They are
  licensed for research use only, are never committed (`local-models/` is Git-ignored) and are
  installed by hand.

**How sure a command is**

- **Verified**: the command was run while this guide was written (2026-10-12, Linux, Python 3.12,
  Node 22) and the result matches what the lesson says. Windows differs only in how you set an
  environment variable and write a path; both forms are shown, and the Windows form is marked
  *unverified here* because the guide was written on Linux.
- **Verified by test**: not run by hand, but a named test that passes proves it.
- **Unverified (reason)**: could not be run in the writing environment (the desktop window, the real
  models, a GPU). The lesson says why, describes what should happen, and cites the code or test that
  proves it.

## The promise about accuracy

Where a lesson describes this repository it describes what is in `main` on **2026-10-12**. The code
and the specifications in [`docs/specs/`](../specs/) are the source of truth. **If a lesson and a
spec disagree, the spec wins and the lesson is out of date**; if a lesson and the code disagree, the
code wins. Where a lesson explains a general idea (what a loop is, what a CNN is) it uses the
simplest honest wording and does not pretend to be a textbook; each folder ends with where to read
more.

When the project changes in a way a learner would notice (a milestone lands, a layer moves, a
decision is reversed), update the lesson and its markers in the same pull request. See
[keeping the guide true](07-walkthrough-and-glossary/05-further-reading-and-keeping-true.md).

## Safety rules for everything in this guide

- The examples create **disposable** libraries in a scratch folder. Never point an experiment at a
  library you care about.
- The pictures used are synthetic (coloured rectangles with noise). Never put real photographs of
  people into an example, a test or a document.
- Nothing from `local-models/` or `evaluation/datasets/` is ever committed, quoted or linked: they hold
  model weights and biometric data. The evaluation lessons describe the scripts and the shape of
  their input, not the data.
