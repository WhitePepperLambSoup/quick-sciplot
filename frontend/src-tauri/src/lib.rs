use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Manager, RunEvent};

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

fn start_backend() -> Option<Child> {
    let backend_dir = project_root().join("backend");
    let python = python_command(&backend_dir);
    let result = Command::new(python)
        .current_dir(&backend_dir)
        .args([
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ])
        .env("PYTHONUNBUFFERED", "1")
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
    let backend = start_backend();
    let builder = tauri::Builder::default().setup(move |app| {
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
