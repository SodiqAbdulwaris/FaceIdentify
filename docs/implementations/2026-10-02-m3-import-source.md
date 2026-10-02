# M3: importing an image as a Source (step 6, second half; TST-036)

Date: 2026-10-02. Spec: API and Contracts sections 5.1, 55 and 57; Persistence section 4.1. Decision note in API and Contracts after section 5.1.

## What was built
- `backend/app/sources/import_source.py`: `ImportSourceUseCase(unit_of_work, store, new_id, clock, max_pixels, max_bytes, checkpoint)` with `import_managed(path, display_name)` and `import_referenced(path, display_name)`, returning `ImportedSource(source_id, artifact_id)`. Errors: `ImportFileError`, `ImportFileTooLargeError` (and `ImageError` / `ReferencedFileError` from the layers it uses). Neither limit has a default.
- `mark_write_not_completed` in `artifact_storage` is now public (it was private), for a caller that runs the three-step protocol itself so that it can make the artifact `AVAILABLE` and add its Source in one transaction.

## Behaviour pinned by the tests
A managed import copies the bytes (hash, size, MIME type and file name recorded; the stored bytes equal the source's) and makes an ACTIVE image Source with the displayed size; a JPEG that the camera turned has its width and height swapped; importing is not processing (no Job, no run); a blank name is refused before the file is looked at; the same file twice is two Sources; concurrent imports all succeed (BEGIN IMMEDIATE queues them); an unsupported, damaged, cut-short, too-large-in-pixels, too-large-in-bytes, missing or directory path leaves no row, no file and no staging file; a write that fails marks the reservation `MISSING` (`WRITE_NOT_COMPLETED`, with the reason) and makes no Source; a crash after the reservation, after the write and after the commit is settled by `recover_artifacts` (no Source for the first two, an unreferenced `AVAILABLE` artifact for the second, and a second recovery changes nothing); the bytes decoded are the bytes stored, even if the file is swapped after it was read; a referenced import copies nothing, records the resolved path and hash, refuses a relative path or one inside the application's own storage, refuses a file that changes between hashing and reading (even to bytes of the same length), and refuses an over-size file before hashing it.

## A finding on the way
The first version checked a referenced file's size after `inspect_referenced_file`, which hashes the whole file, so a huge file would have been read in full before being refused. The size check now comes first and a test proves the file is not inspected.

## Verification
30 tests, 26 mutations caught (on a green baseline), backend coverage 100%. A redundant comparison (the length, implied by the hash) was deleted.
