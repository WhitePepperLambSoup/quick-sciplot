use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager, RunEvent, State};

struct BackendProcess(Mutex<Option<Child>>);

/// Directory that holds the backend's `.env` and `.session_token`.
struct ConfigDir(PathBuf);

const BACKEND_ADDR: &str = "127.0.0.1:8000";
const BACKEND_STARTUP_TIMEOUT: Duration = Duration::from_secs(180);

fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
}

fn app_data_root(app: &AppHandle) -> PathBuf {
    app.path()
        .app_data_dir()
        .unwrap_or_else(|_| project_root().join("backend").join("data"))
}

fn read_session_token(config_dir: &Path) -> Result<String, String> {
    let raw = std::fs::read_to_string(config_dir.join(".session_token"))
        .map_err(|error| format!("session token is unavailable: {error}"))?;
    let token = raw.trim();
    if token.is_empty() {
        return Err("session token is empty".to_string());
    }
    Ok(token.to_string())
}

/// Hands the backend session token to the bundled frontend.
///
/// The packaged window is served from `http://tauri.localhost`, which is
/// cross-site to `http://127.0.0.1:8000`; browsers drop the backend's
/// `SameSite=Strict` session cookie in that setup, so the frontend has to send
/// the token in the `X-Session-Token` header instead.
#[tauri::command]
fn session_token(config: State<'_, ConfigDir>) -> Result<String, String> {
    read_session_token(&config.0)
}

fn python_command(backend_dir: &Path) -> Option<PathBuf> {
    let candidates = if cfg!(target_os = "windows") {
        vec![backend_dir.join(".venv").join("Scripts").join("python.exe")]
    } else {
        vec![backend_dir.join(".venv").join("bin").join("python")]
    };
    candidates.into_iter().find(|path| path.is_file())
}

fn start_backend(app: &AppHandle) -> Option<Child> {
    let data_root = app_data_root(app);
    let data_dir = data_root.join("data");
    let config_dir = data_root.join("config");
    if let Err(error) =
        std::fs::create_dir_all(&data_dir).and_then(|_| std::fs::create_dir_all(&config_dir))
    {
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
    let Some(python) = python_command(&backend_dir) else {
        eprintln!("Quick SciPlot backend Python virtual environment was not found");
        return None;
    };
    launch_backend(python, backend_dir, &data_dir, &config_dir, false)
}

fn launch_backend(
    executable: PathBuf,
    working_dir: PathBuf,
    data_dir: &Path,
    config_dir: &Path,
    sidecar: bool,
) -> Option<Child> {
    let backend_addr: SocketAddr = BACKEND_ADDR.parse().ok()?;
    if !is_port_available(backend_addr) {
        eprintln!("Quick SciPlot backend port {BACKEND_ADDR} is already in use");
        return None;
    }

    let mut command = Command::new(executable);
    command.current_dir(working_dir);
    if sidecar {
        command.args(["--host", "127.0.0.1", "--port", "8000"]);
    } else {
        command.args([
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ]);
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

/// Log whether the backend comes up, without blocking window creation.
///
/// The PyInstaller one-file sidecar unpacks itself on every launch, which can
/// take well over 30 seconds on a busy machine or on first launch while the
/// antivirus scans it.  The shell used to block for ~30 seconds and then kill
/// a backend that was merely slow, leaving the app without a backend; the
/// frontend keeps retrying instead, so a slow start only delays the UI.
fn watch_backend_startup(app: AppHandle) {
    thread::spawn(move || {
        let Ok(address) = BACKEND_ADDR.parse::<SocketAddr>() else {
            return;
        };
        let started = Instant::now();
        while started.elapsed() < BACKEND_STARTUP_TIMEOUT {
            if backend_exited(&app) {
                eprintln!("Quick SciPlot backend exited before it became ready");
                return;
            }
            if TcpStream::connect_timeout(&address, Duration::from_millis(200)).is_ok() {
                return;
            }
            thread::sleep(Duration::from_millis(250));
        }
        eprintln!(
            "Quick SciPlot backend is still not ready at {BACKEND_ADDR} after {}s",
            BACKEND_STARTUP_TIMEOUT.as_secs()
        );
    });
}

fn backend_exited(app: &AppHandle) -> bool {
    let Some(state) = app.try_state::<BackendProcess>() else {
        return true;
    };
    let Ok(mut guard) = state.0.lock() else {
        return true;
    };
    match guard.as_mut() {
        Some(child) => matches!(child.try_wait(), Ok(Some(_))),
        None => true,
    }
}

fn is_port_available(address: SocketAddr) -> bool {
    TcpListener::bind(address).is_ok()
}

fn terminate_child(child: &mut Child) {
    #[cfg(target_os = "windows")]
    let _ = Command::new("taskkill")
        .args(["/PID", &child.id().to_string(), "/T", "/F"])
        .status();
    #[cfg(not(target_os = "windows"))]
    let _ = child.kill();
    let _ = child.wait();
}

fn find_sidecar(app: &AppHandle) -> Option<PathBuf> {
    let resource_dir = app.path().resource_dir().ok()?;
    let target = option_env!("TAURI_ENV_TARGET_TRIPLE").unwrap_or("x86_64-pc-windows-msvc");
    let names = [
        format!("quick-sciplot-backend-{target}.exe"),
        "quick-sciplot-backend.exe".to_string(),
        format!("quick-sciplot-backend-{target}"),
        "quick-sciplot-backend".to_string(),
    ];
    for name in names {
        for path in [
            resource_dir.join(&name),
            resource_dir.join("binaries").join(&name),
        ] {
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
            terminate_child(&mut child);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{is_port_available, read_session_token};
    use std::net::TcpListener;

    #[test]
    fn occupied_port_is_reported_unavailable() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).expect("bind test port");
        let address = listener.local_addr().expect("read test port");

        assert!(!is_port_available(address));
        drop(listener);
        assert!(is_port_available(address));
    }

    #[test]
    fn session_token_is_read_and_trimmed() {
        let dir = std::env::temp_dir().join(format!("quick-sciplot-token-{}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("create temp dir");

        assert!(
            read_session_token(&dir).is_err(),
            "missing file must be an error"
        );

        std::fs::write(dir.join(".session_token"), "  abc123\r\n").expect("write token");
        assert_eq!(read_session_token(&dir).unwrap(), "abc123");

        std::fs::write(dir.join(".session_token"), " \n").expect("write blank token");
        assert!(
            read_session_token(&dir).is_err(),
            "blank token must be an error"
        );

        let _ = std::fs::remove_dir_all(&dir);
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![session_token])
        .setup(|app| {
            let backend = start_backend(app.handle());
            app.manage(ConfigDir(app_data_root(app.handle()).join("config")));
            let started = backend.is_some();
            app.manage(BackendProcess(Mutex::new(backend)));
            if started {
                watch_backend_startup(app.handle().clone());
            }
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
