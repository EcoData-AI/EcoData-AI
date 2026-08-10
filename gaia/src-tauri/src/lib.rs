//! GAIA desktop shell.
//!
//! Responsibilities, in order: start the Python backend, discover the port it
//! bound, create the window with that port injected, and stop the backend when
//! the app exits. The UI itself is the React bundle in `../frontend`.

mod backend;

use std::path::PathBuf;
use std::sync::Mutex;

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

struct BackendState(Mutex<Option<backend::Backend>>);

/// Locate the backend package.
///
/// In a packaged build it is bundled as a resource; in development it sits next
/// to `src-tauri` in the source tree.
fn resolve_backend_dir(app: &tauri::AppHandle) -> PathBuf {
    if let Ok(resource) = app.path().resolve("backend", tauri::path::BaseDirectory::Resource) {
        if resource.join("gaia").is_dir() {
            return resource;
        }
    }
    // Development layout: <repo>/gaia/backend
    let dev = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(|p| p.join("backend"))
        .unwrap_or_default();
    dev
}

fn build_window(app: &tauri::AppHandle, api_base: &str) -> tauri::Result<()> {
    // The frontend reads this to know where the backend is listening. It is set
    // before any application script runs, so the very first fetch is correct.
    let init = format!(
        "window.__GAIA_API_BASE__ = {};",
        serde_json::to_string(api_base).unwrap_or_else(|_| "\"\"".into())
    );

    WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
        .title("GAIA")
        .inner_size(1180.0, 800.0)
        .min_inner_size(760.0, 520.0)
        .center()
        .resizable(true)
        .initialization_script(&init)
        .build()?;
    Ok(())
}

/// Window shown when the backend could not be started.
///
/// A blank window with no explanation is the worst possible failure mode, so
/// the reason is rendered as a self-contained page.
fn build_error_window(app: &tauri::AppHandle, message: &str) -> tauri::Result<()> {
    let escaped = message
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;");
    let html = format!(
        "<!doctype html><meta charset=\"utf-8\"><title>GAIA — startup failed</title>\
         <style>body{{font:14px/1.6 system-ui,sans-serif;margin:0;padding:40px;background:#17181b;\
         color:#ececef}}h1{{font-size:18px;margin:0 0 12px}}pre{{white-space:pre-wrap;background:#1e2024;\
         border:1px solid #2c2f35;border-radius:8px;padding:14px;font-size:12px;color:#a0a3ac}}</style>\
         <h1>GAIA could not start its backend</h1><pre>{escaped}</pre>"
    );
    let url = format!("data:text/html;charset=utf-8,{}", urlencode(&html));

    WebviewWindowBuilder::new(app, "startup-error", WebviewUrl::External(url.parse().unwrap()))
        .title("GAIA — startup failed")
        .inner_size(720.0, 460.0)
        .center()
        .build()?;
    Ok(())
}

fn urlencode(input: &str) -> String {
    input
        .bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                (b as char).to_string()
            }
            _ => format!("%{b:02X}"),
        })
        .collect()
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(BackendState(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();

            // In `tauri dev` the Vite server proxies /api to a backend the
            // developer runs themselves, so the shell must not start a second
            // one — and a relative API base lets the proxy do its job.
            if cfg!(debug_assertions) {
                build_window(&handle, "")?;
                return Ok(());
            }

            let backend_dir = resolve_backend_dir(&handle);
            match backend::start(&backend_dir) {
                Ok(backend) => {
                    let base = backend.base_url();
                    handle
                        .state::<BackendState>()
                        .0
                        .lock()
                        .expect("backend state poisoned")
                        .replace(backend);
                    build_window(&handle, &base)?;
                }
                Err(error) => {
                    build_error_window(&handle, &error.to_string())?;
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to start GAIA")
        .run(|app, event| {
            if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
                if let Some(backend) = app
                    .state::<BackendState>()
                    .0
                    .lock()
                    .ok()
                    .and_then(|mut guard| guard.take())
                {
                    let mut backend = backend;
                    backend.shutdown();
                }
            }
        });
}
