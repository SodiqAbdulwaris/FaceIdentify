# Desktop shell 01 Rust in ten minutes

## 1. What this is and why it exists

You do not need to write Rust to understand this project, but you should be able to *read* the shell, which is about a thousand
lines in four files. Rust is a compiled language that refuses to build code that could crash in certain ways (use after free, data
races, forgotten errors). Its price is strictness; its reward is a small, fast, safe program, which is what you want for the part that
launches and supervises everything else.

## 2. Where it lives

| File | Lines | What |
|---|---|---|
| `desktop/src-tauri/src/main.rs` | 6 | calls `faceidentify_lib::run()` |
| `lib.rs` | 216 | the Tauri app and its commands |
| `config.rs` | 200 | where the library lives; Python path; profile switch (with unit tests) |
| `sidecar.rs` | 574 | starting, handshaking with and stopping the backend (with tests) |
| `Cargo.toml` | | dependencies (`tauri`, `serde`, `base64`, `getrandom`, plugins) |
| `tauri.conf.json` | | window, CSP, bundle |

## 3. How it works

The ideas you meet, each with the line that shows it:

- **`let` and `mut`**: bindings are read-only unless `mut` (`let mut child = ...` in `sidecar.rs`).
- **Types**: `String` (owned text), `&str` (a borrowed view), `PathBuf` (an owned path), `u16`, `u32`, `Option<T>` ("a value or nothing":
  `Option<String>` for "the environment variable, if set"), `Result<T, E>` ("success or an error").
- **`?`** returns early with the error: `fs::create_dir_all(..)?`. Errors are values, not exceptions.
- **`match`** handles every case or the compiler refuses: `match outcome { Ok(sidecar) => ..., Err(error) => ... }`.
- **`struct` / `enum` / `impl`**: data and its methods. `enum BackendStatus { Starting, Ready { connection }, Failed { error } }` is exactly
  the three-way answer the page polls for; `#[derive(Serialize)]` turns it into JSON for free.
- **Ownership**: a value has one owner; passing it moves it. `sidecar.stop(grace)` takes `self` (consumes it), so a stopped sidecar cannot
  be used again. Borrowing (`&config`) lends it without moving.
- **Threads and locks**: `std::thread::spawn` starts the backend off the main thread so the window opens at once; `Mutex<BackendStatus>`
  makes the shared status safe to read from commands while the thread writes it.
- **Attributes** `#[...]` configure the next item: `#[tauri::command]` exposes a function to the page; `#[cfg(test)]` marks test code;
  `#[cfg(windows)]` compiles a block only on Windows (the hidden console window flag).
- **Tests** live beside the code in `#[cfg(test)] mod tests` with `#[test]` functions (run by `cargo test`).
- **`tempfile`** gives tests a throwaway folder.

## 4. Try it

**Works with no models. Verified 2026-10-12 (Linux) for `cargo fmt`; the rest unverified here.** Read `config.rs` (200 lines) first: it is
pure logic with eight small tests in the same file. Then:

```bash
cd desktop/src-tauri
cargo fmt --check        # no output: formatted (observed)
```

*Unverified here:* `cargo test` (needs the Tauri system libraries and a crate download) would run the `config.rs` and `sidecar.rs` tests, and CI
runs them on Windows. Read the test names in `config.rs` as a specification:
`the_environment_beats_the_saved_choice_which_beats_the_default`, `nothing_saved_a_broken_file_or_a_relative_path_all_mean_use_the_default`,
`saving_replaces_the_old_choice_and_leaves_no_temporary_file`, `the_development_profile_follows_the_build_unless_the_environment_decides`.

## 5. Change it

In `config.rs`, `development_profile(Some("banana"), true)` returns `true` ("anything else: the build decides"). If you wanted a stricter
rule you would change the `match`, change its test, and run `cargo test` on Windows. You cannot do it safely without running the tests;
that is why this lesson stops at reading.

## 6. Break it on purpose

Remove a `Some(..)` arm in a `match` over an `Option`: Rust refuses to compile ("non-exhaustive patterns"). The compiler is your
first reviewer. (*Not run here.*)

## 7. Exercises

1. What does `Option<String>` express for an environment variable?
2. Why does `Sidecar::stop` take `self`?
3. Why is the backend started in a thread?

**Answers**

1. Present with a value, or not set.
2. Stopping uses the sidecar up: afterwards it must not exist to be used again.
3. So the window opens immediately and the page polls `backend_status` while the backend starts.

## 8. Related files

- Next: [02 Tauri commands](02-tauri-commands.md)
- [`desktop/src-tauri/src/config.rs`](../../../desktop/src-tauri/src/config.rs), [JavaScript and Rust tools](../01-basics/tools/07-javascript-and-rust-tools.md)
