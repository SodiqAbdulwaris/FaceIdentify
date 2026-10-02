# M3: the runtime package store (step 4b)

Date: 2026-10-02. Specs: Architecture sections 12 and 25.14, Persistence section 28, API and Contracts sections 78 to 80. Closes the interrupted-runtime-installation part of issue 34.

## What was built
- `backend/app/runtime/package_store.py`: `RuntimePackageStore(roots, new_id)` with `install(source, facts)`, `installed()`, `get(key)`, `verify(key)` and `recover()`. Errors: `InvalidPackageError`, `IncompatiblePackageError`, `PackageExistsError`.
- `StorageRoots.runtime_packages` and `StorageRoots.installation` (the published and the staging directories, both machine-local).
- A package key must now be a safe directory name (manifest).
- `recover_on_startup` takes the store and reports `StartupReport.packages` (published and removed count as repairs; directories left or published ones that are not complete are unresolved). `open_library` builds the store and exposes it as `OpenLibrary.packages`.

## The protocol
Validate the manifest, compatibility and the source files (a fast refusal), then copy into `installation/<key>.<token>` while hashing what is written, copy the manifest byte for byte, write the marker last, and publish with one `os.rename`, which fails rather than overwrite. A directory is complete if and only if its marker equals the manifest's hash. Crash handling is derived from the files: a complete staging directory is published at startup, any other is removed, and nothing relies on the crashed process having recorded that it crashed.

## Decisions made while building
Recorded as dated notes in Architecture 12.2 and Persistence section 28, and listed for the owner in the decisions entry (item 8): packages are machine-local, not in the library; an installed package is never replaced; the catalog rows come later.

## Tested
41 store tests (a crash at each of four steps, racing installers over the same and over different packages, damaged and tampered directories, a failing cleanup not hiding the cause) and the startup tests (an interrupted install published, one removed, a second run clean). 46 mutations of the store and the manifest and 5 of the startup wiring, all caught; three redundant guards were deleted (a size check during the copy that the hash makes redundant, a directory test in recovery whose outcome the removal failure already gives). The `fsync` calls are not covered by mutation: durability across a power cut cannot be observed in a test.

## Review
OpenCode (`opencode/big-pickle`, plan agent, disposable worktree, under the watchdog; about 8 minutes). One blocker, fixed: the manifest was the one durable write that was not flushed although the marker vouching for it was; it is now written and flushed like the others, and the guarantee is stated as against a crashed process (no directory entry is flushed on Windows). Majors fixed: a published directory that was not complete blocked its key forever (installing now replaces it, and recovery replaces it with a complete staged copy); an `assert` on an I/O result turned a successful install into a crash (the package is now built from what is already held). Minors fixed: I/O failures are `PackageInstallError`; `os.rename` replaces `os.replace` so publishing cannot overwrite; an export that lies inside another export is refused by the manifest; `left` records why; a failing first checkpoint no longer leaks an empty staging directory; a staging entry that is not `<key>.<token>` is left alone; the `installed()` docstring no longer overclaims. Noted, not changed: the racing-installer tests run both installers on one thread (the single-process precondition is documented).
