# Walkthrough 05 Further reading and keeping this true

## 1. What this is and why it exists

Two last things: where to go when this guide runs out, and how to stop the guide itself going stale. A learning guide that is wrong is worse
than none.

## 2. Where it lives

This folder: `docs/guides/learning/`. The old single-file guide is now a short redirect, `docs/research/codebase-learning-guide.md`, kept so old links still land.

## 3. How it works

**Further reading**

- Python: the official tutorial (docs.python.org/3/tutorial); *Automate the Boring Stuff with Python* for beginners; *Fluent Python* later.
- SQL and SQLite: sqlite.org (especially "Write-Ahead Logging" and "Isolation in SQLite"); the SQLAlchemy 2.0 tutorial; the Alembic documentation.
- Web: MDN Web Docs (developer.mozilla.org) for HTML, CSS, JavaScript and HTTP; the FastAPI tutorial; the React documentation (react.dev); the
  TypeScript handbook; the TanStack Query docs; the Tailwind docs.
- Rust and Tauri: *The Rust Programming Language* ("the book", free online); v2.tauri.app.
- Machine learning: 3Blue1Brown's neural-network series for intuition; the ArcFace paper ("ArcFace: Additive Angular Margin Loss for Deep Face
  Recognition"); the InsightFace repository; the ONNX Runtime documentation on execution providers.
- Software practice: *The Pragmatic Programmer*; Martin Kleppmann's *Designing Data-Intensive Applications* for transactions, recovery and the outbox pattern.

(These are general references from the old guide. This session did not open them again.)

**Keeping this guide true**

- This guide describes `main` as of **2026-10-12**. When the project changes in a way a learner would notice (a milestone lands, a layer moves, a
  decision is reversed, a command changes), update the affected lesson, its **[built]/[designed]/[researched]** markers and its "Verified" date in the same pull
  request, as the documentation rules require for the other status documents.
- **Spec wins.** When a lesson and a spec disagree, the spec is right and the lesson needs the fix. Do not edit a spec to match a lesson.
- **A lesson never claims a command it did not run.** Mark anything unrun *unverified* and say why. When you re-run a lesson's commands, update its date.
- **Link check.** Every relative link must resolve. This check needs no dependency (run from the repository folder):

  ```bash
  python3 - <<'EOF'
  import pathlib, re, sys, urllib.parse
  root = pathlib.Path("docs/guides/learning")
  bad = []
  for md in root.rglob("*.md"):
      for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", md.read_text(encoding="utf-8")):
          if target.startswith(("http:", "https:", "mailto:")):
              continue
          if not (md.parent / urllib.parse.unquote(target)).resolve().exists():
              bad.append(f"{md}: {target}")
  print("\n".join(bad) or "all relative links resolve")
  sys.exit(1 if bad else 0)
  EOF
  ```

- **Size.** Keep each lesson to about 400 lines or fewer; split a big one rather than growing it.
- **Safety.** Never put real personal data, photographs, tokens or secrets in a lesson, and do not describe the contents of `evaluation/datasets/`.

## 4. Try it

**Works with no models. Verified 2026-10-12.** Run the link check above. Expected output: `all relative links resolve` and exit code 0. Then run the same check
after breaking a link on purpose (rename a file in a scratch copy) to see it list the broken one.

## 5. Change it

Add a lesson: a file named `NN-topic.md` in the matching folder following the eight-part shape (what and why, where it lives, how it works, Try it, Change it,
Break it on purpose, exercises with answers, related files), a row in that folder's README and in the [index](../README.md), and its links checked.

## 6. Break it on purpose

Delete a file a lesson links to (in a scratch branch): the link check names the lesson and the missing target. That is why the check is run before every
pull request that touches these folders.

## 7. Exercises

1. What do you update when a command in a lesson changes?
2. Which wins when a lesson and a spec disagree?

**Answers**

1. The lesson, its marker if the status changed, and its "Verified" date, in the same pull request.
2. The spec.

## 8. Related files

- Previous: [04 Glossary](04-glossary.md) · Up: [Walkthrough and glossary](README.md)
- [`docs/guides/learning/README.md`](../README.md), [`.agents/rules/documentation.md`](../../../../.agents/rules/documentation.md)
