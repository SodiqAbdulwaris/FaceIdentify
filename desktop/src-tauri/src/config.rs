//! Where the library lives, and how the backend is found: the shell owns both (architecture 22).
//!
//! The library root is chosen, in order, by the environment (`FACEIDENTIFY_LIBRARY_ROOT`, for
//! development and tests), the user's saved choice, then a default under the application's data
//! directory. The saved choice is one small JSON file the shell writes; nothing else is stored here.

use crate::sidecar::module_entry;
use serde::{Deserialize, Serialize};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

pub const LIBRARY_ROOT_ENV: &str = "FACEIDENTIFY_LIBRARY_ROOT";
pub const LOCAL_STATE_ENV: &str = "FACEIDENTIFY_LOCAL_STATE_ROOT";
pub const PYTHON_ENV: &str = "FACEIDENTIFY_PYTHON";
pub const DEVELOPMENT_PROFILE_ENV: &str = "FACEIDENTIFY_DEVELOPMENT_PROFILE";
const SETTINGS_FILE: &str = "shell.json";

/// The image formats the backend can import (JPEG, PNG, BMP, WebP, AVIF): what the picker offers.
pub const IMAGE_EXTENSIONS: &[&str] = &["jpg", "jpeg", "png", "bmp", "webp", "avif"];
/// The video files the backend imports by name (M6 step 3; `VIDEO_SUFFIXES` in the backend).
pub const VIDEO_EXTENSIONS: &[&str] = &["mp4", "m4v", "mov", "mkv", "webm", "avi"];

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

/// The machine-local state root (models, policies, indexes): `FACEIDENTIFY_LOCAL_STATE_ROOT` when
/// set (installer checks and tests keep it away from the real one), else the default.
pub fn resolve_local_state_root(from_environment: Option<String>, default: PathBuf) -> PathBuf {
    from_environment
        .filter(|value| !value.is_empty())
        .map_or(default, PathBuf::from)
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

/// The folder the installer puts the frozen backend in, beside the application's other resources.
pub const PACKAGED_BACKEND_DIR: &str = "faceidentify-backend";
const PACKAGED_BACKEND_EXE: &str = "faceidentify-backend.exe";

/// What to run to start the host, and from where.
#[derive(Debug, PartialEq, Eq)]
pub struct Launch {
    pub program: PathBuf,
    pub entry: Vec<String>,
    pub working_dir: PathBuf,
}

/// How the backend is started. `FACEIDENTIFY_PYTHON` wins (development and the tests that name an
/// interpreter); otherwise the frozen backend the installer shipped, when it is there; otherwise the
/// repository's own environment. A packaged build needs no Python on the machine.
pub fn resolve_launch(
    python_from_environment: Option<String>,
    resource_dir: Option<&Path>,
    repository: &Path,
) -> Launch {
    let packaged = resource_dir
        .map(|dir| dir.join(PACKAGED_BACKEND_DIR))
        .filter(|dir| dir.join(PACKAGED_BACKEND_EXE).is_file());
    match (
        python_from_environment.filter(|value| !value.is_empty()),
        packaged,
    ) {
        (None, Some(dir)) => Launch {
            program: dir.join(PACKAGED_BACKEND_EXE),
            entry: Vec::new(),
            working_dir: dir,
        },
        (python, _) => Launch {
            program: resolve_python(python, repository),
            entry: module_entry(),
            working_dir: repository.to_path_buf(),
        },
    }
}

/// The library folder when the user has chosen none: `Documents\FaceIdentify`, where the user can see
/// and back it up and no uninstaller option can reach it (M8 decision R8). A library that already
/// exists at the older default under the application's data folder keeps being used.
pub fn default_library_root(documents: Option<PathBuf>, legacy: PathBuf) -> PathBuf {
    let has_library = legacy.join("database").join("library.db").is_file();
    match documents {
        Some(documents) if !has_library => documents.join("FaceIdentify"),
        _ => legacy,
    }
}

/// The origins the web view is served from, which the host must be told to answer (the web
/// view is a different origin from the loopback server). The packaged app's origin on Windows
/// (`http` or `https` by Tauri's setting) and on the other platforms; in a debug build also the
/// Vite dev server named in `tauri.conf.json`.
pub fn web_view_origins(debug_build: bool) -> Vec<String> {
    let mut origins = vec![
        "http://tauri.localhost".to_string(),
        "https://tauri.localhost".to_string(),
        "tauri://localhost".to_string(),
    ];
    if debug_build {
        origins.push("http://localhost:5173".to_string());
    }
    origins
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
    fn the_dev_server_is_an_allowed_origin_only_in_a_debug_build() {
        let release = web_view_origins(false);
        let debug = web_view_origins(true);

        assert!(release.contains(&"http://tauri.localhost".to_string()));
        assert!(!release.iter().any(|o| o.contains("5173")));
        assert!(debug.contains(&"http://localhost:5173".to_string()));
        assert!(debug.iter().all(|o| !o.contains('*')));
    }

    #[test]
    fn the_picker_offers_exactly_the_formats_the_backend_imports() {
        assert_eq!(
            IMAGE_EXTENSIONS,
            ["jpg", "jpeg", "png", "bmp", "webp", "avif"]
        );
        assert_eq!(
            VIDEO_EXTENSIONS,
            ["mp4", "m4v", "mov", "mkv", "webm", "avi"]
        );
    }

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
    fn the_local_state_root_comes_from_the_environment_unless_it_is_empty() {
        let default = PathBuf::from("default");
        assert_eq!(
            resolve_local_state_root(Some("scratch".into()), default.clone()),
            PathBuf::from("scratch")
        );
        assert_eq!(
            resolve_local_state_root(Some(String::new()), default.clone()),
            default
        );
        assert_eq!(resolve_local_state_root(None, default.clone()), default);
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

    fn packaged_backend(resources: &Path) {
        let dir = resources.join(PACKAGED_BACKEND_DIR);
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join(PACKAGED_BACKEND_EXE), "").unwrap();
    }

    #[test]
    fn a_packaged_build_runs_its_own_backend_without_python() {
        let resources = tempfile::tempdir().unwrap();
        packaged_backend(resources.path());

        let launch = resolve_launch(None, Some(resources.path()), Path::new("repo"));

        let dir = resources.path().join(PACKAGED_BACKEND_DIR);
        assert_eq!(launch.program, dir.join(PACKAGED_BACKEND_EXE));
        assert!(launch.entry.is_empty(), "the frozen host has no -m module");
        assert_eq!(launch.working_dir, dir);
    }

    #[test]
    fn python_from_the_environment_beats_a_packaged_backend() {
        let resources = tempfile::tempdir().unwrap();
        packaged_backend(resources.path());

        let launch = resolve_launch(
            Some("C:/py/python.exe".into()),
            Some(resources.path()),
            Path::new("repo"),
        );

        assert_eq!(launch.program, PathBuf::from("C:/py/python.exe"));
        assert_eq!(launch.entry, ["-m", "backend.api.host"]);
        assert_eq!(launch.working_dir, PathBuf::from("repo"));
    }

    #[test]
    fn without_a_packaged_backend_the_repository_environment_runs_the_module() {
        let empty = tempfile::tempdir().unwrap();
        let folder_only = tempfile::tempdir().unwrap();
        fs::create_dir_all(folder_only.path().join(PACKAGED_BACKEND_DIR)).unwrap();

        for resources in [None, Some(empty.path()), Some(folder_only.path())] {
            let launch = resolve_launch(None, resources, Path::new("repo"));
            assert!(
                launch.program.to_string_lossy().contains("python"),
                "{launch:?}"
            );
            assert_eq!(launch.entry, ["-m", "backend.api.host"]);
            assert_eq!(launch.working_dir, PathBuf::from("repo"));
        }
    }

    #[test]
    fn the_default_library_is_in_documents_unless_one_already_exists_at_the_old_place() {
        let dir = tempfile::tempdir().unwrap();
        let documents = dir.path().join("Documents");
        let legacy = dir.path().join("AppData").join("library");

        assert_eq!(
            default_library_root(Some(documents.clone()), legacy.clone()),
            documents.join("FaceIdentify")
        );
        assert_eq!(
            default_library_root(None, legacy.clone()),
            legacy,
            "no Documents folder known: the old place"
        );

        fs::create_dir_all(legacy.join("database")).unwrap();
        assert_eq!(
            default_library_root(Some(documents.clone()), legacy.clone()),
            documents.join("FaceIdentify"),
            "an empty folder is not a library"
        );
        fs::write(legacy.join("database").join("library.db"), "").unwrap();
        assert_eq!(
            default_library_root(Some(documents), legacy.clone()),
            legacy
        );
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
