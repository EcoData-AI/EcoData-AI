//! Supervises the Python backend process.
//!
//! The desktop shell owns the backend's lifetime: it starts it on launch, reads
//! the port it bound from stdout, and kills it on exit. The backend also
//! watches its parent PID, so if the shell is killed rather than closed cleanly
//! the server still exits instead of lingering.

use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::time::Duration;

/// How long to wait for the backend to announce its port before giving up.
const STARTUP_TIMEOUT: Duration = Duration::from_secs(90);

pub struct Backend {
    child: Child,
    pub port: u16,
}

impl Backend {
    pub fn base_url(&self) -> String {
        format!("http://127.0.0.1:{}", self.port)
    }

    pub fn shutdown(&mut self) {
        // The child installs no signal handler beyond uvicorn's, so kill is the
        // reliable cross-platform stop. All state is already committed to
        // SQLite by the time a turn's `done` event has been sent.
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

#[derive(Debug)]
pub enum StartError {
    NoPython(Vec<PathBuf>),
    Spawn(String),
    Timeout,
    Exited(String),
}

impl std::fmt::Display for StartError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            StartError::NoPython(tried) => write!(
                f,
                "Could not find a Python interpreter for the GAIA backend.\n\nLooked in:\n{}\n\n\
                 Run the installer script (scripts/install.sh or scripts/install.ps1), or set \
                 GAIA_PYTHON to a Python 3.10+ interpreter that has the gaia package installed.",
                tried
                    .iter()
                    .map(|p| format!("  • {}", p.display()))
                    .collect::<Vec<_>>()
                    .join("\n")
            ),
            StartError::Spawn(detail) => {
                write!(f, "Could not start the GAIA backend process.\n\n{detail}")
            }
            StartError::Timeout => write!(
                f,
                "The GAIA backend did not finish starting in time.\n\nCheck the log in your GAIA \
                 data directory for details."
            ),
            StartError::Exited(detail) => write!(
                f,
                "The GAIA backend stopped while starting up.\n\n{detail}"
            ),
        }
    }
}

/// Candidate interpreters, in priority order.
///
/// A virtualenv created by the installer next to the bundled backend wins, so a
/// packaged install never depends on whatever `python3` happens to be on PATH.
fn python_candidates(backend_dir: &Path) -> Vec<PathBuf> {
    let mut candidates = Vec::new();

    if let Ok(explicit) = std::env::var("GAIA_PYTHON") {
        if !explicit.trim().is_empty() {
            candidates.push(PathBuf::from(explicit));
        }
    }

    let venv_bin = if cfg!(windows) { "Scripts" } else { "bin" };
    let exe = if cfg!(windows) { "python.exe" } else { "python3" };
    candidates.push(backend_dir.join(".venv").join(venv_bin).join(exe));
    if cfg!(windows) {
        candidates.push(backend_dir.join(".venv").join(venv_bin).join("python.exe"));
    } else {
        candidates.push(backend_dir.join(".venv").join(venv_bin).join("python"));
    }

    candidates.push(PathBuf::from(if cfg!(windows) { "python" } else { "python3" }));
    candidates
}

fn is_usable(path: &Path) -> bool {
    // An absolute path must exist; a bare name is resolved via PATH by the OS,
    // so defer that check to the spawn attempt.
    if path.components().count() > 1 {
        path.is_file()
    } else {
        true
    }
}

pub fn start(backend_dir: &Path) -> Result<Backend, StartError> {
    let candidates = python_candidates(backend_dir);
    let mut last_error: Option<String> = None;

    for python in candidates.iter().filter(|p| is_usable(p)) {
        match try_spawn(python, backend_dir) {
            Ok(backend) => return Ok(backend),
            Err(StartError::Spawn(detail)) => {
                last_error = Some(detail);
                continue;
            }
            // A process that started and then failed is a real error worth
            // surfacing — do not silently fall through to the next candidate.
            Err(other) => return Err(other),
        }
    }

    match last_error {
        Some(detail) => Err(StartError::Spawn(detail)),
        None => Err(StartError::NoPython(candidates)),
    }
}

fn try_spawn(python: &Path, backend_dir: &Path) -> Result<Backend, StartError> {
    let mut command = Command::new(python);
    command
        .arg("-m")
        .arg("gaia")
        .arg("--print-port")
        .arg("--parent-pid")
        .arg(std::process::id().to_string())
        .current_dir(backend_dir)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        // Unbuffered stdout, so the port line arrives immediately rather than
        // sitting in a pipe buffer until the process exits.
        .env("PYTHONUNBUFFERED", "1");

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = command
        .spawn()
        .map_err(|e| StartError::Spawn(format!("{}: {e}", python.display())))?;

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| StartError::Spawn("no stdout pipe".into()))?;
    let stderr = child.stderr.take();

    // Read the announcement on a worker thread so a hung child cannot block the
    // UI thread forever.
    let (sender, receiver) = mpsc::channel::<Result<u16, String>>();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            let Ok(line) = line else { break };
            if let Ok(value) = serde_json::from_str::<serde_json::Value>(&line) {
                if value.get("event").and_then(|v| v.as_str()) == Some("listening") {
                    if let Some(port) = value.get("port").and_then(|v| v.as_u64()) {
                        let _ = sender.send(Ok(port as u16));
                        // Keep draining stdout so the child never blocks on a
                        // full pipe.
                        continue;
                    }
                }
            }
        }
        let _ = sender.send(Err("backend stdout closed".into()));
    });

    match receiver.recv_timeout(STARTUP_TIMEOUT) {
        Ok(Ok(port)) => Ok(Backend { child, port }),
        Ok(Err(_)) | Err(mpsc::RecvTimeoutError::Disconnected) => {
            let detail = drain_stderr(stderr);
            let _ = child.kill();
            Err(StartError::Exited(detail))
        }
        Err(mpsc::RecvTimeoutError::Timeout) => {
            let _ = child.kill();
            Err(StartError::Timeout)
        }
    }
}

fn drain_stderr(stderr: Option<std::process::ChildStderr>) -> String {
    let Some(stderr) = stderr else {
        return "The backend produced no output.".into();
    };
    let lines: Vec<String> = BufReader::new(stderr)
        .lines()
        .map_while(Result::ok)
        .collect();
    if lines.is_empty() {
        "The backend produced no output.".into()
    } else {
        // The tail is where the traceback lands.
        lines
            .iter()
            .rev()
            .take(15)
            .rev()
            .cloned()
            .collect::<Vec<_>>()
            .join("\n")
    }
}
