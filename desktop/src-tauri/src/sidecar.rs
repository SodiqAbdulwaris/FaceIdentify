//! The sidecar: start the Python API host, read its one-line handshake, and stop it cleanly.
//!
//! The contract with `python -m backend.api.host` (decided 2026-10-06, built in M4 W1 and W6):
//!
//! * the per-launch capability (token) is generated here, from the operating system's random
//!   source, and handed over **only** in the environment (`FACEIDENTIFY_LAUNCH_TOKEN`), never on
//!   the command line;
//! * the host binds `127.0.0.1` on a port it picks and writes exactly one JSON line to stdout;
//! * `--parent-pid` makes the host stop if this process dies, and `--stdin-lifeline` makes it stop
//!   gracefully when the pipe we keep open on its standard input is closed (on Windows there is no
//!   gentle signal, so closing the pipe is how a clean stop is requested).

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use serde::{Deserialize, Serialize};
use std::fmt;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

pub const TOKEN_ENV: &str = "FACEIDENTIFY_LAUNCH_TOKEN";
pub const PROTOCOL: &str = "faceidentify.v1";
pub const LOOPBACK: &str = "127.0.0.1";
const HANDSHAKE_SCHEMA_VERSION: u32 = 1;

#[derive(Debug)]
pub enum SidecarError {
    Token(String),
    Spawn(std::io::Error),
    /// No handshake line arrived in time.
    NoHandshake,
    /// The host ended before it wrote its handshake.
    Exited(Option<i32>),
    BadHandshake(String),
}

impl fmt::Display for SidecarError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SidecarError::Token(why) => write!(f, "could not make a launch token: {why}"),
            SidecarError::Spawn(why) => write!(f, "could not start the backend: {why}"),
            SidecarError::NoHandshake => write!(f, "the backend did not report that it was ready"),
            SidecarError::Exited(Some(code)) => {
                write!(f, "the backend stopped while starting (exit code {code})")
            }
            SidecarError::Exited(None) => write!(f, "the backend stopped while starting"),
            SidecarError::BadHandshake(why) => {
                write!(f, "the backend's handshake is invalid: {why}")
            }
        }
    }
}

impl std::error::Error for SidecarError {}

/// The line the host prints once it is accepting connections.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct Handshake {
    pub schema_version: u32,
    pub protocol: String,
    pub host: String,
    pub port: u16,
    pub pid: u32,
}

/// Parse and validate the handshake: the host must be loopback, on a real port, speaking the
/// protocol this shell knows. Anything else is refused rather than trusted.
pub fn parse_handshake(line: &str) -> Result<Handshake, SidecarError> {
    let handshake: Handshake = serde_json::from_str(line.trim())
        .map_err(|error| SidecarError::BadHandshake(error.to_string()))?;
    if handshake.schema_version != HANDSHAKE_SCHEMA_VERSION {
        return Err(SidecarError::BadHandshake(
            "unknown handshake version".into(),
        ));
    }
    if handshake.protocol != PROTOCOL {
        return Err(SidecarError::BadHandshake("unknown protocol".into()));
    }
    if handshake.host != LOOPBACK {
        return Err(SidecarError::BadHandshake(
            "the backend is not on loopback".into(),
        ));
    }
    if handshake.port == 0 {
        return Err(SidecarError::BadHandshake("no port".into()));
    }
    Ok(handshake)
}

/// A fresh 256-bit capability: URL-safe base64 without padding, the one text form the host accepts.
pub fn generate_token() -> Result<String, SidecarError> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|error| SidecarError::Token(error.to_string()))?;
    Ok(URL_SAFE_NO_PAD.encode(bytes))
}

/// Where and how to start the host.
#[derive(Debug, Clone)]
pub struct SidecarConfig {
    pub python: PathBuf,
    /// The directory `backend` is imported from (the repository root in development).
    pub working_dir: PathBuf,
    pub library_root: PathBuf,
    pub local_state_root: PathBuf,
    /// The fake catalog and perception under an uncalibrated policy: never a release setting.
    pub development_profile: bool,
}

impl SidecarConfig {
    /// The command to run. The token is in the environment, never in the arguments.
    pub fn command(&self, token: &str, parent_pid: u32) -> Command {
        let mut command = Command::new(&self.python);
        command
            .current_dir(&self.working_dir)
            .args(["-m", "backend.api.host", "--library-root"])
            .arg(&self.library_root)
            .arg("--local-state-root")
            .arg(&self.local_state_root)
            .arg("--parent-pid")
            .arg(parent_pid.to_string())
            .arg("--stdin-lifeline");
        if self.development_profile {
            command.arg("--development-profile");
        }
        command
            .env(TOKEN_ENV, token)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: no console flashes up
        }
        command
    }
}

/// What the web view needs to talk to the backend.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Connection {
    pub base_url: String,
    pub events_url: String,
    pub token: String,
    pub protocol: String,
}

impl Connection {
    fn new(handshake: &Handshake, token: String) -> Self {
        let address = format!("{}:{}", handshake.host, handshake.port);
        Connection {
            base_url: format!("http://{address}"),
            events_url: format!("ws://{address}/api/v1/events"),
            token,
            protocol: handshake.protocol.clone(),
        }
    }
}

/// A running host. Dropping the value does not stop it; call [`Sidecar::stop`].
pub struct Sidecar {
    child: Child,
    stdin: Option<ChildStdin>,
    connection: Connection,
}

/// Start the host and wait for its handshake. On any failure the child is gone before this returns.
pub fn start(config: &SidecarConfig, timeout: Duration) -> Result<Sidecar, SidecarError> {
    let token = generate_token()?;
    let mut child = config
        .command(&token, std::process::id())
        .spawn()
        .map_err(SidecarError::Spawn)?;
    let stdin = child.stdin.take();
    if let Some(stderr) = child.stderr.take() {
        thread::spawn(move || {
            for_each_line(
                BufReader::new(stderr),
                |line| log::warn!(target: "backend", "{line}"),
            );
        });
    }
    let stdout = child.stdout.take().expect("stdout is piped");
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        let mut first = Vec::new();
        let outcome = reader
            .read_until(b'\n', &mut first)
            .map(|_| String::from_utf8_lossy(&first).into_owned());
        let _ = sender.send(outcome);
        // Keep draining so the host never blocks writing to a pipe nobody reads.
        for_each_line(reader, drop);
    });
    let outcome = match receiver.recv_timeout(timeout) {
        Ok(Ok(line)) if !line.trim().is_empty() => parse_handshake(&line),
        Ok(_) => Err(SidecarError::Exited(wait_briefly(&mut child))),
        Err(_) => Err(SidecarError::NoHandshake),
    };
    match outcome {
        Ok(handshake) => {
            let connection = Connection::new(&handshake, token);
            Ok(Sidecar {
                child,
                stdin,
                connection,
            })
        }
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            Err(error)
        }
    }
}

/// Read a pipe to its end, a line at a time, whatever bytes it carries: text that is not valid
/// UTF-8 (a Windows code page in a traceback) is shown with replacement characters and never ends
/// the reading early, because a child whose pipe fills up would block.
fn for_each_line(mut reader: impl BufRead, mut each: impl FnMut(String)) {
    let mut line = Vec::new();
    loop {
        line.clear();
        match reader.read_until(b'\n', &mut line) {
            Ok(0) | Err(_) => return,
            Ok(_) => each(String::from_utf8_lossy(&line).trim_end().to_string()),
        }
    }
}

/// The exit code of a child that has just closed its output (a moment to be reaped).
fn wait_briefly(child: &mut Child) -> Option<i32> {
    let deadline = Instant::now() + Duration::from_secs(2);
    while Instant::now() < deadline {
        if let Ok(Some(status)) = child.try_wait() {
            return status.code();
        }
        thread::sleep(Duration::from_millis(20));
    }
    None
}

impl Sidecar {
    pub fn connection(&self) -> &Connection {
        &self.connection
    }

    #[cfg(test)]
    pub fn is_running(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }

    /// Ask for a clean stop (close the pipe the host watches), wait up to `grace` for it to finish
    /// closing the library, then end it if it has not. Returns whether it stopped on its own.
    pub fn stop(mut self, grace: Duration) -> bool {
        drop(self.stdin.take());
        let deadline = Instant::now() + grace;
        while Instant::now() < deadline {
            if let Ok(Some(_)) = self.child.try_wait() {
                return true;
            }
            thread::sleep(Duration::from_millis(50));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::Path;

    const GOOD: &str = r#"{"schema_version":1,"protocol":"faceidentify.v1","host":"127.0.0.1","port":50123,"pid":42}"#;

    fn python() -> PathBuf {
        PathBuf::from(std::env::var("FACEIDENTIFY_PYTHON").unwrap_or_else(|_| "python".into()))
    }

    /// A stand-in `backend.api.host` in a temporary directory: the module the shell would run.
    fn fake_host(dir: &Path, body: &str) -> SidecarConfig {
        let package = dir.join("backend").join("api");
        fs::create_dir_all(&package).unwrap();
        fs::write(dir.join("backend").join("__init__.py"), "").unwrap();
        fs::write(package.join("__init__.py"), "").unwrap();
        fs::write(package.join("host.py"), body).unwrap();
        SidecarConfig {
            python: python(),
            working_dir: dir.to_path_buf(),
            library_root: dir.join("library"),
            local_state_root: dir.join("state"),
            development_profile: false,
        }
    }

    fn prints_then_waits(handshake: &str) -> String {
        format!("import sys\nprint('{handshake}', flush=True)\nsys.stdin.read()\n")
    }

    #[test]
    fn a_token_is_256_bits_of_url_safe_unpadded_base64_and_never_repeats() {
        let first = generate_token().unwrap();
        let second = generate_token().unwrap();

        assert_eq!(first.len(), 43);
        assert!(first
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_'));
        assert_eq!(URL_SAFE_NO_PAD.decode(&first).unwrap().len(), 32);
        assert_ne!(first, second);
    }

    #[test]
    fn the_handshake_is_accepted_only_when_it_is_loopback_on_a_port_and_our_protocol() {
        let handshake = parse_handshake(GOOD).unwrap();
        assert_eq!((handshake.port, handshake.pid), (50123, 42));
        assert!(parse_handshake(&format!("{GOOD}\n")).is_ok());

        for bad in [
            GOOD.replace("127.0.0.1", "0.0.0.0"),
            GOOD.replace("127.0.0.1", "192.168.1.5"),
            GOOD.replace("faceidentify.v1", "other.v2"),
            GOOD.replace("50123", "0"),
            GOOD.replace("\"schema_version\":1", "\"schema_version\":2"),
            "not json".to_string(),
            "{}".to_string(),
            String::new(),
        ] {
            assert!(
                matches!(parse_handshake(&bad), Err(SidecarError::BadHandshake(_))),
                "{bad}"
            );
        }
    }

    #[test]
    fn the_command_carries_the_token_only_in_the_environment() {
        let config = SidecarConfig {
            python: "python".into(),
            working_dir: "work".into(),
            library_root: "lib".into(),
            local_state_root: "state".into(),
            development_profile: false,
        };
        let token = "T".repeat(43);

        let command = config.command(&token, 4242);

        let args: Vec<String> = command
            .get_args()
            .map(|a| a.to_string_lossy().into())
            .collect();
        assert!(
            !args.iter().any(|a| a.contains(&token)),
            "the token must not be an argument"
        );
        assert_eq!(
            args,
            [
                "-m",
                "backend.api.host",
                "--library-root",
                "lib",
                "--local-state-root",
                "state",
                "--parent-pid",
                "4242",
                "--stdin-lifeline",
            ]
        );
        let env: Vec<_> = command
            .get_envs()
            .filter(|(key, _)| *key == TOKEN_ENV)
            .map(|(_, value)| value.map(|v| v.to_string_lossy().into_owned()))
            .collect();
        assert_eq!(env, [Some(token)]);
        assert_eq!(command.get_current_dir(), Some(Path::new("work")));
    }

    #[test]
    fn the_development_profile_is_requested_only_when_configured() {
        let mut config = SidecarConfig {
            python: "python".into(),
            working_dir: ".".into(),
            library_root: "l".into(),
            local_state_root: "s".into(),
            development_profile: false,
        };
        let has_flag = |config: &SidecarConfig| {
            config
                .command("t", 1)
                .get_args()
                .any(|a| a == "--development-profile")
        };

        assert!(!has_flag(&config));
        config.development_profile = true;
        assert!(has_flag(&config));
    }

    #[test]
    fn a_started_host_reports_its_connection_and_stops_cleanly_when_asked() {
        let dir = tempfile::tempdir().unwrap();
        let config = fake_host(dir.path(), &prints_then_waits(GOOD));

        let mut sidecar = start(&config, Duration::from_secs(30)).unwrap();

        let connection = sidecar.connection().clone();
        assert_eq!(connection.base_url, "http://127.0.0.1:50123");
        assert_eq!(connection.events_url, "ws://127.0.0.1:50123/api/v1/events");
        assert_eq!(connection.protocol, PROTOCOL);
        assert_eq!(connection.token.len(), 43);
        assert!(sidecar.is_running());
        assert!(
            sidecar.stop(Duration::from_secs(30)),
            "it should leave when its pipe closes"
        );
    }

    #[test]
    fn a_host_that_does_not_stop_when_asked_is_ended_after_the_grace_period() {
        let dir = tempfile::tempdir().unwrap();
        let body = format!(
            "import time\nprint('{}', flush=True)\ntime.sleep(600)\n",
            GOOD.replace('"', "\\\"")
        );
        let config = fake_host(dir.path(), &body);
        let sidecar = start(&config, Duration::from_secs(30)).unwrap();

        let stopped_itself = sidecar.stop(Duration::from_millis(300));

        assert!(!stopped_itself);
    }

    #[test]
    fn a_host_that_never_reports_is_ended_and_reported() {
        let dir = tempfile::tempdir().unwrap();
        let config = fake_host(dir.path(), "import time\ntime.sleep(600)\n");

        let error = start(&config, Duration::from_millis(500)).err().unwrap();

        assert!(matches!(error, SidecarError::NoHandshake));
    }

    /// A stand-in that keeps writing a heartbeat file, so a test can tell whether it is alive.
    fn heartbeat_host(dir: &Path, announcement: &str) -> (SidecarConfig, PathBuf) {
        let beat = dir.join("heartbeat.txt");
        let body = format!(
            "import time
{announcement}
n = 0
while True:
    n += 1
    open(r'{}', 'w').write(str(n))
    time.sleep(0.02)
",
            beat.display()
        );
        (fake_host(dir, &body), beat)
    }

    fn assert_stopped_beating(beat: &Path) {
        thread::sleep(Duration::from_millis(500)); // let the process end and the file settle
        let first = fs::read_to_string(beat).unwrap();
        thread::sleep(Duration::from_millis(500));
        assert_eq!(
            fs::read_to_string(beat).unwrap(),
            first,
            "the failed host is still running"
        );
    }

    #[test]
    fn a_pipe_is_read_to_its_end_even_when_a_line_is_not_valid_utf8() {
        let bytes: &[u8] = b"first\ncaf\xe9 and more\nlast without newline";
        let mut lines = Vec::new();

        for_each_line(bytes, |line| lines.push(line));

        assert_eq!(
            lines,
            ["first", "caf\u{fffd} and more", "last without newline"]
        );
    }

    #[test]
    fn a_host_that_fails_to_start_properly_is_not_left_running() {
        for announcement in ["", "print('hello', flush=True)"] {
            let dir = tempfile::tempdir().unwrap();
            let (config, beat) = heartbeat_host(dir.path(), announcement);

            let error = start(&config, Duration::from_millis(800)).err().unwrap();

            assert!(
                matches!(
                    error,
                    SidecarError::NoHandshake | SidecarError::BadHandshake(_)
                ),
                "{error}"
            );
            assert_stopped_beating(&beat);
        }
    }

    #[test]
    fn a_host_that_exits_before_reporting_is_reported_with_its_exit_code() {
        let dir = tempfile::tempdir().unwrap();
        let config = fake_host(dir.path(), "import sys\nsys.exit(3)\n");

        let error = start(&config, Duration::from_secs(30)).err().unwrap();

        assert!(matches!(error, SidecarError::Exited(Some(3))), "{error}");
    }

    #[test]
    fn a_host_that_reports_nonsense_is_ended_and_refused() {
        let dir = tempfile::tempdir().unwrap();
        let config = fake_host(
            dir.path(),
            "import time\nprint('hello', flush=True)\ntime.sleep(600)\n",
        );

        let error = start(&config, Duration::from_secs(30)).err().unwrap();

        assert!(matches!(error, SidecarError::BadHandshake(_)));
    }

    #[test]
    fn a_missing_program_is_a_spawn_error() {
        let dir = tempfile::tempdir().unwrap();
        let mut config = fake_host(dir.path(), "");
        config.python = dir.path().join("no-such-python");

        let error = start(&config, Duration::from_secs(1)).err().unwrap();

        assert!(matches!(error, SidecarError::Spawn(_)));
    }

    /// The real host, over the real contract: run with `cargo test -- --ignored` after `uv sync`.
    #[test]
    #[ignore = "needs the repository's Python environment"]
    fn the_real_host_starts_with_the_development_profile_and_stops_cleanly() {
        let repository = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let dir = tempfile::tempdir().unwrap();
        let config = SidecarConfig {
            python: std::env::var("FACEIDENTIFY_PYTHON")
                .map(PathBuf::from)
                .unwrap_or_else(|_| repository.join(".venv").join("Scripts").join("python.exe")),
            working_dir: repository,
            library_root: dir.path().join("library"),
            local_state_root: dir.path().join("state"),
            development_profile: true,
        };
        fs::create_dir_all(&config.library_root).unwrap();

        let sidecar = start(&config, Duration::from_secs(120)).unwrap();

        assert!(sidecar
            .connection()
            .base_url
            .starts_with("http://127.0.0.1:"));
        assert!(
            sidecar.stop(Duration::from_secs(60)),
            "a clean exit, not a kill"
        );
    }
}
