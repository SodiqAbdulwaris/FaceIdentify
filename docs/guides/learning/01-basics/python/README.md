# Python, from zero, inside this repository

The backend is about 14,500 lines of application Python (plus about 9,400 lines of API,
infrastructure and worker code, and a test suite of about 3,000 tests). These seven lessons teach the language in the order you meet it.
Each one ends with exercises you run **in this repository**, against real files.

| # | Lesson | Covers |
|---|---|---|
| 01 | [Values, operators, strings and collections](01-values-and-collections.md) | what a program is, types, variables, operators, strings, list/tuple/dict/set, JSON |
| 02 | [Conditions and loops](02-conditions-and-loops.md) | `if`, truthiness, chained comparison, `for`, `while`, comprehensions |
| 03 | [Functions and errors](03-functions-and-errors.md) | parameters, keyword-only, functions as values (`clock`, `new_id`), closures, exceptions |
| 04 | [Classes, dataclasses and enums](04-classes-dataclasses-enums.md) | objects, `@dataclass(frozen=True)`, `StrEnum`, `Protocol` |
| 05 | [Modules, types, files and hashes](05-modules-types-files.md) | imports, `python -m`, type hints and mypy, paths, bytes, SHA-256, atomic writes, `with` |
| 06 | [Iterators, decorators and concurrency](06-iterators-decorators-concurrency.md) | generators, `@decorator`, threads, processes, `async`/`await` |
| 07 | [Read a real function](07-read-a-real-function.md) | the recognition policy, line by line, run for real |

## How to try the snippets

Start an interactive Python in the project's environment, from the repository folder:

```bash
uv run python
```

You see a `>>>` prompt. Type a line, press Enter, see the result. Leave with Ctrl+D (Linux, macOS) or
Ctrl+Z then Enter (Windows). Snippets longer than a few lines are shown with the output they
produced on 2026-10-12; you can paste them whole.

A **comment** starts with `#` and Python ignores it. A **docstring** is a string in triple quotes at
the top of a file, class or function: documentation tools can read. This repository's files nearly always
start with one that explains the file's purpose, and those docstrings are often the best explanation
you will find. Read them first.

Back to [01 Basics](../README.md) · [guide index](../../README.md).
