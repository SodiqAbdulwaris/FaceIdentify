//! Where the library lives, and how the backend is found: the shell owns both (architecture 22).
//!
//! The library root is chosen, in order, by the environment (`FACEIDENTIFY_LIBRARY_ROOT`, for
//! development and tests), the user's saved choice, then a default under the application's data
//! directory. The saved choice is one small JSON file the shell writes; nothing else is stored here.

use serde::{Deserialize, Serialize};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

pub const LIBRARY_ROOT_ENV: &str = "FACEIDENTIFY_LIBRARY_ROOT";
pub const PYTHON_ENV: &str = "FACEIDENTIFY_PYTHON";
pub const DEVELOPMENT_PROFILE_ENV: &str = "FACEIDENTIFY_DEVELOPMENT_PROFILE";
const SETTINGS_FILE: &str = "shell.json";

#[derive(Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
struct Saved {
    library_root: Option<PathBuf>,
}

fn settings_path(config_dir: &Path) -> PathBuf {
    config_dir.join(SETTINGS_FILE)
}

/// The library root the user saved, if there is a usable record of one. A missing or unreadable
/// file is "nothing saved", never an error: the default applies.
pub fn load_saved_library_root(config_dir: &Path) -> Option<PathBuf> {
    let text = fs::read_to_string(settings_path(config_dir)).ok()?;
    let saved: Saved = serde_json::from_str(&text).ok()?;
    saved.library_root.filter(|root| root.is_absolute())
}

/// Remember the user's choice (the shell restarts the backend, or the app, to use it).
pub fn save_library_root(config_dir: &Path, root: &Path) -> io::Result<()> {
    fs::create_dir_all(config_dir)?;
    let text = serde_json::to_string_pretty(&Saved {
        library_root: Some(root.to_path_buf()),
    })
    .map_err(io::Error::other)?;
    // Write beside it, then replace: a crash leaves the old choice or the new one, never half.
    let temporary = config_dir.join(format!("{SETTINGS_FILE}.tmp"));
    fs::write(&temporary, text)?;
    fs::rename(&temporary, settings_path(config_dir))
}

/// Which root to use: the environment, then the saved choice, then the default.
pub fn resolve_library_root(
    from_environment: Option<String>,
    saved: Option<PathBuf>,
    default: PathBuf,
) -> PathBuf {
    from_environment
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .or(saved)
        .unwrap_or(default)
}

/// The Python that runs the backend. In development that is the repository's own environment; a
/// packaged build ships its own (M8). `FACEIDENTIFY_PYTHON` overrides either.
pub fn resolve_python(from_environment: Option<String>, repository: &Path) -> PathBuf {
    match from_environment.filter(|value| !value.is_empty()) {
        Some(path) => PathBuf::from(path),
        None => {
            let scripts = if cfg!(windows) { "Scripts" } else { "bin" };
            let name = if cfg!(windows) {
                "python.exe"
            } else {
                "python"
            };
            repository.join(".venv").join(scripts).join(name)
        }
    }
}

/// Whether the backend runs with the fake catalog and perception. On in debug builds (so the
/// workflow can be tried before real models exist), off in release builds; the environment can
/// say either way. Never a release setting.
pub fn development_profile(from_environment: Option<String>, debug_build: bool) -> bool {
    match from_environment.as_deref() {
        Some("1") | Some("true") => true,
        Some("0") | Some("false") => false,
        _ => debug_build,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_saved_library_root_round_trips() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("my library");

        save_library_root(&dir.path().join("config"), &root).unwrap();

        assert_eq!(
            load_saved_library_root(&dir.path().join("config")),
            Some(root)
        );
    }

    #[test]
    fn saving_replaces_the_old_choice_and_leaves_no_temporary_file() {
        let dir = tempfile::tempdir().unwrap();
        let first = dir.path().join("one");
        let second = dir.path().join("two");

        save_library_root(dir.path(), &first).unwrap();
        save_library_root(dir.path(), &second).unwrap();

        assert_eq!(load_saved_library_root(dir.path()), Some(second));
        let names: Vec<_> = fs::read_dir(dir.path())
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect();
        assert_eq!(names, [std::ffi::OsString::from(SETTINGS_FILE)]);
    }

    #[test]
    fn nothing_saved_a_broken_file_or_a_relative_path_all_mean_use_the_default() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(load_saved_library_root(dir.path()), None);

        fs::write(settings_path(dir.path()), "{ not json").unwrap();
        assert_eq!(load_saved_library_root(dir.path()), None);

        fs::write(
            settings_path(dir.path()),
            r#"{"library_root":"relative/path"}"#,
        )
        .unwrap();
        assert_eq!(load_saved_library_root(dir.path()), None);

        fs::write(settings_path(dir.path()), r#"{}"#).unwrap();
        assert_eq!(load_saved_library_root(dir.path()), None);
    }

    #[test]
    fn the_environment_beats_the_saved_choice_which_beats_the_default() {
        let default = PathBuf::from("default");
        let saved = Some(PathBuf::from("saved"));

        assert_eq!(
            resolve_library_root(Some("env".into()), saved.clone(), default.clone()),
            PathBuf::from("env")
        );
        assert_eq!(
            resolve_library_root(None, saved.clone(), default.clone()),
            PathBuf::from("saved")
        );
        assert_eq!(
            resolve_library_root(Some(String::new()), saved, default.clone()),
            PathBuf::from("saved"),
            "an empty variable is not a choice"
        );
        assert_eq!(resolve_library_root(None, None, default.clone()), default);
    }

    #[test]
    fn python_comes_from_the_environment_or_the_repository_environment() {
        let repository = Path::new("repo");

        assert_eq!(
            resolve_python(Some("C:/py/python.exe".into()), repository),
            PathBuf::from("C:/py/python.exe")
        );
        let found = resolve_python(None, repository);
        assert!(
            found.starts_with("repo/.venv") || found.starts_with("repo\\.venv"),
            "{found:?}"
        );
        assert!(found.to_string_lossy().contains("python"));
        assert_eq!(resolve_python(Some(String::new()), repository), found);
    }

    #[test]
    fn the_development_profile_follows_the_build_unless_the_environment_decides() {
        assert!(development_profile(None, true));
        assert!(!development_profile(None, false));
        assert!(development_profile(Some("1".into()), false));
        assert!(development_profile(Some("true".into()), false));
        assert!(!development_profile(Some("0".into()), true));
        assert!(!development_profile(Some("false".into()), true));
        assert!(
            development_profile(Some("banana".into()), true),
            "anything else: the build decides"
        );
    }
}
