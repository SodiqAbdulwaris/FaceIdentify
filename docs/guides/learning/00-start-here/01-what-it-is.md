# 01 What FaceIdentify is

## 1. What this is and why it exists

FaceIdentify is a **Windows desktop application that remembers people by their faces, on your own
computer**. You give it photographs. It finds the faces, turns each face into a list of numbers,
compares that list with the lists it has seen before, and decides one of three things for each face:

1. **This is someone I already know.** The face is attached to that person's memory. (`MATCH_EXISTING`)
2. **This is someone new.** A new memory is started. (`CREATE_NEW`)
3. **I am not sure.** Nothing is decided automatically; the face waits for you to place it by hand.
   (`ABSTAIN`)

You can then name a person, correct a wrong guess, merge two memories that are really one person,
split one that is really two, search by name, and search by a picture of a face. Nothing leaves your
machine: there is no cloud, no account and no network service in the design. It is a personal tool.

The owner's rule, repeated all through the project: **a wrong automatic guess is worse than no guess.**
That one idea explains most of the caution you will meet in the code: thresholds, abstaining,
evidence records, "pending" data that stays private until it is accepted, and an automatic matcher
that is currently switched off until its quality has been measured on verified data.

## 2. Where it lives

| Question | Look here |
|---|---|
| What is built, what is not, right now | [`docs/plans/PROJECT_STATUS.md`](../../../plans/PROJECT_STATUS.md) |
| The product requirements | [`docs/specs/product-definition-and-requirements-v1.md`](../../../specs/product-definition-and-requirements-v1.md) |
| The decisions the owner has made | [`.agents/CONTEXT.md`](../../../../.agents/CONTEXT.md) (dated `Decision` notes) |
| The locked technology choices | [`docs/research/tech-stack.md`](../../../research/tech-stack.md) |

## 3. How it works (the product, in four sentences)

- A **Source** is something you imported (today, a still image; video and cameras are planned).
- Processing a source finds **Observations** (detected faces), gives each a **Representation** (its
  512 numbers), compares it with every remembered Representation, and lets a **reasoner** decide.
- Decisions are grouped into **Identities** (one visual subject each). An Identity may be linked to a
  **Person** (a name you gave).
- Every decision and every correction leaves **Evidence**, an append-only record of why.

The vocabulary is taught properly in [03-backend/domain](../03-backend/domain/README.md).

### What is built today (2026-10-12)

| Area | State |
|---|---|
| Import still images, process them in the background, see faces and people | [built] |
| Name people, confirm / move / separate a face, place an unplaced face | [built] |
| Merge identities, split faces off an identity | [built] |
| Recycle bin, restore, permanent delete of a source, forget an identity or a person | [built] |
| Search by name and history; search by a picture of a face (saves nothing) | [built] |
| Real models (`buffalo_l`) on CPU or an NVIDIA GPU under an abstain-first policy | [built]; the model files are installed by hand and never committed |
| Fake models (the *development profile*) so everything can be tried with no model files | [built] |
| The desktop window that starts and stops the backend | [built] |
| Measuring recognition quality (scripts in `evaluation/`) | [built]; needs local-only data |
| Calibrated **automatic** matching | [designed]; blocked until a verified evaluation set exists (TST-057B) |
| Movies (M6), cameras (M7), installer and packaged runtime (M8) | [designed]; not started |

> The owner decided on 2026-10-08 that cross-source recognition is *assisted* first: the system ranks
> possible matches and you confirm. *Automatic* recognition is a separate, later claim.

## 4. Try it (works with no models)

Verified on 2026-10-12. You need the repository and `uv sync` done ([lesson 06](06-set-up-your-machine.md)).

1. Open `docs/plans/PROJECT_STATUS.md` and find the row for **M5**. Read the line "Not built yet".
2. See the three outcomes as code, with a test for each:

   ```bash
   uv run pytest tests/unit/test_recognition_reasoner.py -q
   ```

   Expected: a row of dots and `59 passed` in under a second. The reasoner is the small piece of code
   that returns `MATCH_EXISTING`, `CREATE_NEW` or `ABSTAIN`.
3. See that the backend is a program you can start, with its options:

   ```bash
   uv run python -m backend.api.host --help
   ```

   Expected: a usage text listing `--library-root`, `--local-state-root`, `--parent-pid`,
   `--development-profile` and `--stdin-lifeline`. There is no option for the secret token, on
   purpose (lesson 02).

## 5. Change it

Nothing here changes code. The one safe "change" is to the documents: when you learn something that
this lesson gets wrong, fix the lesson in a branch (see
[git and pull requests](../01-basics/tools/05-git-and-pull-requests.md)). Run the link check described
in [keeping the guide true](../07-walkthrough-and-glossary/05-further-reading-and-keeping-true.md)
afterwards.

## 6. Break it on purpose

Run the host with no arguments:

```bash
uv run python -m backend.api.host
```

Expected: an `argparse` usage error ending `the following arguments are required: --library-root,
--local-state-root`, and exit code 2. The program refuses to start without knowing where the library
is. Run it with both folders but without `FACEIDENTIFY_LAUNCH_TOKEN` set and it prints
`backend.api.host: FACEIDENTIFY_LAUNCH_TOKEN is not set` and exits 2 (verified by reading
`main()` in `backend/api/host.py` and by `tests/integration/test_api_host.py`).

## 7. Exercises

1. In one sentence each, what do `MATCH_EXISTING`, `CREATE_NEW` and `ABSTAIN` mean?
2. Why is "I am not sure" an allowed answer instead of always picking the best guess?
3. Which of these needs an internet connection: importing a photo, processing it, searching by name?
4. Find in `PROJECT_STATUS.md` what is *not* built yet and name two things you therefore cannot try.

**Answers**

1. Known person: attach to them. New person: start a new memory. Not sure: do nothing automatic and
   leave the face for you.
2. Because a false accept (putting a stranger's face in someone's memory) is worse than a false
   reject (you place the face by hand). See [thresholds and errors](../01-basics/recognition-ideas/05-thresholds-and-errors.md).
3. None. There is no network service in the design.
4. For example movies and cameras (M6, M7), and an installer or packaged runtime (M8); also calibrated
   automatic matching.

## 8. Related files

- Next: [02 The four programs](02-the-four-programs.md)
- [Domain vocabulary](../03-backend/domain/01-vocabulary.md)
- [Product definition](../../../specs/product-definition-and-requirements-v1.md)
