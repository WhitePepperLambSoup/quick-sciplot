use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{AppHandle, Manager, RunEvent};

struct BackendProcess(Mutex<Option<Child>>);

fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
}

fn python_command(backend_dir: &PathBuf) -> PathBuf {
    let candidates = if cfg!(target_os = "windows") {
        vec![backend_dir.join(".venv").join("Scripts").join("python.exe")]
    } else {
        vec![backend_dir.join(".venv").join("bin").join("python")]
    };
    candidates
        .into_iter()
        .find(|path| path.is_file())
        .unwrap_or_else(|| PathBuf::from("python"))
}

fn start_backend(app: &AppHandle) -> Option<Child> {
    let data_root = app
        .path()
        .app_data_dir()
        .unwrap_or_else(|_| project_root().join("backend").join("data"));
    let data_dir = data_root.join("data");
    let config_dir = data_root.join("config");
    if let Err(error) = std::fs::create_dir_all(&data_dir).and_then(|_| std::fs::create_dir_all(&config_dir)) {
        eprintln!("Quick SciPlot data directory could not be created: {error}");
        return None;
    }

    if let Some(sidecar) = find_sidecar(app) {
        return launch_backend(
            sidecar.clone(),
            sidecar.parent().unwrap_or(&data_root).to_path_buf(),
            &data_dir,
            &config_dir,
            true,
        );
    }

    let backend_dir = project_root().join("backend");
    let python = python_command(&backend_dir);
    launch_backend(python, backend_dir, &data_dir, &config_dir, false)
}

fn launch_backend(
    executable: PathBuf,
    working_dir: PathBuf,
    data_dir: &PathBuf,
    config_dir: &PathBuf,
    sidecar: bool,
) -> Option<Child> {
    let mut command = Command::new(executable);
    command.current_dir(working_dir);
    if sidecar {
        command.args(["--host", "127.0.0.1", "--port", "8000"]);
    } else {
        command.args(["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"]);
    }
    let result = command
        .env("PYTHONUNBUFFERED", "1")
        .env("DATA_DIR", data_dir)
        .env("QUICK_SCIPLOT_CONFIG_DIR", config_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();

    match result {
        Ok(child) => Some(child),
        Err(error) => {
            eprintln!("Quick SciPlot backend could not start: {error}");
            None
        }
    }
}

fn find_sidecar(app: &AppHandle) -> Option<PathBuf> {
    let resource_dir = app.path().resource_dir().ok()?;
    let target = option_env!("TAURI_ENV_TARGET_TRIPLE").unwrap_or("x86_64-pc-windows-msvc");
    let names = [
        format!("quick-sciplot-backend-{target}.exe"),
        "quick-sciplot-backend.exe".to_string(),
    ];
    for name in names {
        for path in [resource_dir.join(&name), resource_dir.join("binaries").join(&name)] {
            if path.is_file() {
                return Some(path);
            }
        }
    }
    None
}

fn stop_backend(state: &BackendProcess) {
    if let Ok(mut process) = state.0.lock() {
        if let Some(mut child) = process.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default().setup(|app| {
        let backend = start_backend(app.handle());
        app.manage(BackendProcess(Mutex::new(backend)));
        Ok(())
    });

    builder
        .build(tauri::generate_context!())
        .expect("error while building Quick SciPlot")
        .run(|app_handle, event| {
            if matches!(event, RunEvent::Exit) {
                if let Some(state) = app_handle.try_state::<BackendProcess>() {
                    stop_backend(&state);
                }
            }
        });
}
