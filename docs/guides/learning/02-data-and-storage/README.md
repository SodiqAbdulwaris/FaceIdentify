# 02 Data and storage

Everything the application "knows" lives in two places: a **SQLite database** and a **folder of files**,
plus a rebuildable vector index. These nine lessons teach you to read the persistence code, from SQL basics
up to the rules that keep the data safe, and every one lets you look at a real database that your own run
produced.

| # | Lesson | You will learn |
|---|---|---|
| 01 | [SQL and tables](01-sql-and-tables.md) | tables, keys, SQL, constraints; query the library you made in lesson 07 |
| 02 | [SQLite, WAL and the pragmas](02-sqlite-and-wal.md) | why one file, what WAL is, the per-connection settings, how to copy a database safely |
| 03 | [Transactions and the unit of work](03-transactions-and-unit-of-work.md) | ACID, `BEGIN IMMEDIATE`, busy retry, the `revision` column |
| 04 | [Migrations with Alembic](04-migrations-alembic.md) | the schema history, running it, and exactly how to add a column (described, not committed) |
| 05 | [SQLAlchemy and repositories](05-sqlalchemy-and-repositories.md) | rows as Python objects, sessions, queries, repositories |
| 06 | [The vector index and the outbox](06-vector-index-and-outbox.md) | `IndexOperation`, the coordinator, generations, rebuilds |
| 07 | [Erasure](07-erasure.md) | forgetting a face for real, step by step |
| 08 | [Storage roots and artifacts](08-storage-roots-and-artifacts.md) | the two roots, managed versus referenced files, safe keys, the library lock |
| 09 | [Read a database and a log](09-read-a-database-and-a-log.md) | the practical toolkit: sqlite3 in Python, the CLI if you have it, backups, reading stderr and the diagnostic id |

All "Try it" sections use the scratch library from [lesson 07 of start-here](../00-start-here/07-run-it-and-see-it-work.md)
(`~/faceidentify-play`). Do those steps first; the lessons assume it holds a few processed pictures.

Back to the [guide index](../README.md).
