//! The desktop shell: it owns the library location, starts the Python backend as a sidecar, hands
//! the web view the one connection it may use, and stops the backend cleanly when it ends.

mod config;
mod sidecar;

use serde::Serialize;
use sidecar::{Connection, Sidecar, SidecarConfig};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Manager, RunEvent, State};
use tauri_plugin_dialog::DialogExt;

/// How long the backend may take to report that it is serving (a cold start runs migrations).
const START_TIMEOUT: Duration = Duration::from_secs(120);
/// How long it may take to close the library after being asked to stop.
const STOP_GRACE: Duration = Duration::from_secs(10);

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
enum BackendStatus {
    Starting,
    Ready { connection: Connection },
    Failed { error: String },
}

struct Backend {
    status: Mutex<BackendStatus>,
    sidecar: Mutex<Option<Sidecar>>,
    library_root: PathBuf,
    config_dir: PathBuf,
}

#[derive(Serialize)]
struct LibraryInfo {
    library_root: String,
}

/// Where the backend is (or why it is not): the web view polls this until it is ready.
#[tauri::command]
fn backend_status(backend: State<'_, Backend>) -> BackendStatus {
    backend.status.lock().expect("status lock").clone()
}

#[tauri::command]
fn library_info(backend: State<'_, Backend>) -> LibraryInfo {
    LibraryInfo {
        library_root: backend.library_root.display().to_string(),
    }
}

/// Let the user pick the library folder. The choice is saved and takes effect at the next start
/// (changing the library under a running backend is not supported).
#[tauri::command]
async fn choose_library(app: AppHandle) -> Result<Option<String>, String> {
    let picked = tauri::async_runtime::spawn_blocking({
        let app = app.clone();
        move || app.dialog().file().blocking_pick_folder()
    })
    .await
    .map_err(|error| error.to_string())?;
    let Some(folder) = picked else {
        return Ok(None);
    };
    let root = folder.into_path().map_err(|error| error.to_string())?;
    let backend = app.state::<Backend>();
    config::save_library_root(&backend.config_dir, &root).map_err(|error| error.to_string())?;
    Ok(Some(root.display().to_string()))
}

/// Let the user pick one picture to search with. Like `choose_images`, only the path crosses to the
/// web view: the backend reads the file itself, once, and saves nothing.
#[tauri::command]
async fn choose_picture(app: AppHandle) -> Result<Option<String>, String> {
    let picked = tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .add_filter("Images", config::IMAGE_EXTENSIONS)
            .blocking_pick_file()
    })
    .await
    .map_err(|error| error.to_string())?;
    Ok(picked
        .and_then(|file| file.into_path().ok())
        .map(|path| path.display().to_string()))
}

/// Let the user pick images to import. The backend reads the files itself (it is on the same
/// machine), so only their paths cross to the web view.
#[tauri::command]
async fn choose_images(app: AppHandle) -> Result<Vec<String>, String> {
    let picked = tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .add_filter("Images", config::IMAGE_EXTENSIONS)
            .blocking_pick_files()
    })
    .await
    .map_err(|error| error.to_string())?;
    Ok(picked
        .unwrap_or_default()
        .into_iter()
        .filter_map(|file| file.into_path().ok())
        .map(|path| path.display().to_string())
        .collect())
}

fn repository_root() -> PathBuf {
    let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
    manifest
        .join("..")
        .join("..")
        .canonicalize()
        .unwrap_or_else(|_| manifest.to_path_buf())
}

fn start_backend(app: &AppHandle) {
    let backend = app.state::<Backend>();
    let local_state_root = app
        .path()
        .app_local_data_dir()
        .unwrap_or_else(|_| std::env::temp_dir().join("FaceIdentify"))
        .join("state");
    let repository = repository_root();
    let config = SidecarConfig {
        python: config::resolve_python(std::env::var(config::PYTHON_ENV).ok(), &repository),
        working_dir: repository,
        library_root: backend.library_root.clone(),
        local_state_root,
        development_profile: config::development_profile(
            std::env::var(config::DEVELOPMENT_PROFILE_ENV).ok(),
            cfg!(debug_assertions),
        ),
    };
    let handle = app.clone();
    std::thread::spawn(move || {
        let backend = handle.state::<Backend>();
        let outcome = fs::create_dir_all(&config.library_root)
            .map_err(|error| format!("could not create the library folder: {error}"))
            .and_then(|_| {
                sidecar::start(&config, START_TIMEOUT).map_err(|error| error.to_string())
            });
        match outcome {
            Ok(sidecar) => {
                *backend.status.lock().expect("status lock") = BackendStatus::Ready {
                    connection: sidecar.connection().clone(),
                };
                *backend.sidecar.lock().expect("sidecar lock") = Some(sidecar);
            }
            Err(error) => {
                log::error!("the backend did not start: {error}");
                *backend.status.lock().expect("status lock") = BackendStatus::Failed { error };
            }
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        // First: a second launch must reach this instance before anything else starts.
        .plugin(tauri_plugin_single_instance::init(
            |app, _arguments, _directory| {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.unminimize();
                    let _ = window.set_focus();
                }
            },
        ))
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            backend_status,
            library_info,
            choose_library,
            choose_images,
            choose_picture
        ])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            let config_dir = app.path().app_config_dir()?;
            let default_root = app.path().app_data_dir()?.join("library");
            let library_root = config::resolve_library_root(
                std::env::var(config::LIBRARY_ROOT_ENV).ok(),
                config::load_saved_library_root(&config_dir),
                default_root,
            );
            app.manage(Backend {
                status: Mutex::new(BackendStatus::Starting),
                sidecar: Mutex::new(None),
                library_root,
                config_dir,
            });
            start_backend(app.handle());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            let backend = handle.state::<Backend>();
            let sidecar = backend.sidecar.lock().expect("sidecar lock").take();
            if let Some(sidecar) = sidecar {
                sidecar.stop(STOP_GRACE);
            }
        }
    });
}
