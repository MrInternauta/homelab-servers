#!/usr/bin/env python3
#
# stack-guard.py — start every stack at boot once its requirements are met, then
# keep them running. Linux only; meant to run as a systemd service (see
# install-autostart.sh). Standard library only.
#
# Usage:
#   ./stack-guard.py run              # wait for requirements, start, watch (the service)
#   ./stack-guard.py check            # run the requirement checks once, exit 0/1
#   ./stack-guard.py status           # one line per stack
#   ./stack-guard.py run --pull       # pull images before the first start
#   ./stack-guard.py run --dry-run    # check and show what would start, change nothing
#
# Stacks listed in STACK_GUARD_SKIP (root .env, comma-separated) are left alone.
#
import argparse
import collections
import http.client
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Same order as restart-all.sh.
STACKS = [
    "audiobookshelf",
    "coolify",
    "papra-doc",
    "home-assistant",
    "jellyfin",
    "immich-photos",
    "portainer",
    "obsidian-brain",
]

# Same probes as test-services.sh, keyed by the stack that serves them.
PROBES = [
    ("portainer", "portainer", 9000),
    ("jellyfin", "jellyfin", 8096),
    ("immich-photos", "immich", 2283),
    ("home-assistant", "homeassistant", 8123),
    ("papra-doc", "papra", 1221),
    ("audiobookshelf", "audiobookshelf", 13378),
    ("obsidian-brain", "obsidian", 3000),
    ("coolify", "coolify", 8000),
]
# A login redirect or a 401 still proves the service is listening.
PROBE_OK = {200, 301, 302, 400, 401, 403}

REQUIREMENT_RETRY = 30  # seconds between requirement checks at boot
WATCH_INTERVAL = 60  # seconds between watch passes
PROBE_INTERVAL = 300  # seconds between HTTP probe rounds
DOCKER_WAIT = 120  # seconds to wait for the Docker daemon on each check
MAX_RESTARTS = 3  # per stack ...
RESTART_WINDOW = 600  # ... within this many seconds
STORAGE_FAILS = 3  # consecutive failed storage checks before stopping the stacks

stop_event = threading.Event()


def log(tag, msg):
    print(f"[{tag}] {msg}" if tag else msg, flush=True)


# ── Helpers ──────────────────────────────────────────────────────────────────
def read_env(path):
    """Parse KEY=VALUE lines without sourcing the file."""
    values = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip("\"'")
    except OSError:
        pass
    return values


def run_timed(cmd, timeout, stderr=True):
    """Run cmd, never blocking past timeout + a few seconds.

    A command touching a dead `hard` NFS mount can sit in uninterruptible sleep
    and ignore SIGKILL, so don't wait for it forever after killing it.
    Returns (returncode or None on timeout, output). stderr=False drops stderr,
    for commands whose stdout gets parsed (compose prints warnings on stderr).
    """
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if stderr else subprocess.DEVNULL,
            text=True,
        )
    except OSError as e:
        return 127, str(e)
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out or ""
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return None, ""


def tcp_open(host, port, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def sleep(seconds):
    """Sleep, waking early on SIGTERM. Returns False if we should stop."""
    return not stop_event.wait(seconds)


# ── Stacks ───────────────────────────────────────────────────────────────────
class Stack:
    def __init__(self, name, root_env):
        self.name = name
        self.dir = os.path.join(ROOT_DIR, name)
        self.compose = self._running_compose_file()
        for fname in ("docker-compose.yml", "docker-compose.yaml"):
            if self.compose:
                break
            if os.path.isfile(os.path.join(self.dir, fname)):
                self.compose = os.path.join(self.dir, fname)
        self.has_env = os.path.isfile(os.path.join(self.dir, ".env"))
        self.restarts = collections.deque()
        self.paused_until = None  # set when the restart budget runs out
        self.uses_storage = self._uses_storage(root_env)

    def _running_compose_file(self):
        """The compose file this stack's containers were started from, if it is
        still in the stack directory (e.g. portainer/compose-with-tsdproxy.yaml),
        so starting it again doesn't swap the variant."""
        code, out = run_timed(
            ["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project.working_dir={self.dir}",
             "--format", '{{.Label "com.docker.compose.project.config_files"}}'], 20, stderr=False)
        if code != 0:
            return None
        for line in out.splitlines():
            path = line.split(",")[0].strip()
            if os.path.dirname(path) == self.dir and os.path.isfile(path):
                return path
        return None

    def _uses_storage(self, root_env):
        """True if the stack mounts anything from EXTERNAL_STORAGE / APPDATA_ROOT."""
        if not self.compose:
            return False
        with open(self.compose) as f:
            # Only variable references count — comments mention APPDATA_ROOT too.
            text = "\n".join(line.split("#", 1)[0] for line in f)
        used = set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", text))
        if used & {"APPDATA_ROOT", "EXTERNAL_STORAGE"}:
            return True
        storage = root_env.get("EXTERNAL_STORAGE", "")
        if not storage:
            return False
        # A literal host path such as papra-doc's /mnt/backup/papra/documents.
        if re.search(re.escape(storage) + r"(/|:|\s|$)", text):
            return True
        # e.g. coolify's COOLIFY_STORAGE may point onto the external disk. Only
        # look at variables the compose file uses: configure.sh copies the shared
        # paths into every .env whether or not the stack mounts them.
        env = read_env(os.path.join(self.dir, ".env"))
        return any(v == storage or v.startswith(storage + "/") for k, v in env.items() if k in used)

    def compose_cmd(self, *args):
        return ["docker", "compose", "-f", self.compose, *args]

    def containers(self):
        """Containers of this stack as dicts, or None if compose failed."""
        code, out = run_timed(self.compose_cmd("ps", "-a", "--format", "json"), 30, stderr=False)
        if code != 0:
            return None
        out = out.strip()
        try:
            if out.startswith("["):
                return json.loads(out)
            return [json.loads(line) for line in out.splitlines() if line.strip()]
        except ValueError:
            return None

    def problems(self, items=None):
        """List of (service, reason) for containers that are not up and healthy."""
        if items is None:
            items = self.containers()
        if items is None:
            return [("*", "docker compose ps failed")]
        if not items:
            return [("*", "no containers")]
        bad = []
        for c in items:
            state, health = c.get("State", ""), c.get("Health", "")
            if state != "running":
                bad.append((c.get("Service", "?"), state or "unknown"))
            elif health == "unhealthy":
                bad.append((c.get("Service", "?"), "unhealthy"))
        return bad

    def up(self, pull=False, dry_run=False):
        cmds = []
        if pull:
            cmds.append(self.compose_cmd("pull", "--quiet"))
        cmds.append(self.compose_cmd("up", "-d", "--remove-orphans"))
        for cmd in cmds:
            if dry_run:
                log("DRY", " ".join(cmd))
                continue
            code, out = run_timed(cmd, 900)
            if code != 0:
                log("FAIL", f"{self.name} — {cmd[4]} failed" + (" (timed out)" if code is None else ""))
                if out.strip():
                    log("", "    " + out.strip().replace("\n", "\n    "))
                return False
        return True

    def stop(self):
        code, _ = run_timed(self.compose_cmd("stop"), 180)
        return code == 0

    def restart(self):
        code, _ = run_timed(self.compose_cmd("restart"), 300)
        return code == 0

    def stub_mounts(self, storage, fstype):
        """Container paths bound from storage that, inside a running container,
        are not on the storage filesystem — i.e. Docker started it from its
        restart policy before the share was mounted, on an empty stub dir."""
        stubs = []
        for c in self.containers() or []:
            if c.get("State") != "running":
                continue
            code, out = run_timed(["docker", "inspect", "-f", "{{.State.Pid}} {{json .Mounts}}", c["ID"]], 20, stderr=False)
            if code != 0:
                continue
            pid, _, mounts = out.strip().partition(" ")
            try:
                with open(f"/proc/{pid}/mountinfo") as f:
                    # mount point (field 5) -> fstype (first field after " - ")
                    table = {line.split()[4]: line.split(" - ", 1)[1].split()[0] for line in f}
            except (OSError, IndexError):
                continue
            for m in json.loads(mounts or "[]"):
                src, dst = m.get("Source", ""), m.get("Destination", "")
                if (src == storage or src.startswith(storage + "/")) and table.get(dst.replace(" ", "\\040")) != fstype:
                    stubs.append(f"{c.get('Service', '?')}:{dst}")
        return stubs

    def restart_services(self, services):
        code, _ = run_timed(self.compose_cmd("restart", *services), 300)
        return code == 0


def load_stacks():
    root_env = read_env(os.path.join(ROOT_DIR, ".env"))
    skip = {s.strip() for s in root_env.get("STACK_GUARD_SKIP", "").split(",") if s.strip()}
    active, skipped = [], []
    for name in STACKS:
        stack = Stack(name, root_env)
        if name in skip:
            skipped.append((stack, "in STACK_GUARD_SKIP"))
        elif not stack.compose:
            skipped.append((stack, "no docker-compose file"))
        elif not stack.has_env:
            skipped.append((stack, "no .env — run ./configure.sh first"))
        else:
            active.append(stack)
    return root_env, active, skipped


# ── Requirement checks ───────────────────────────────────────────────────────
def check_docker(wait=DOCKER_WAIT):
    deadline = time.monotonic() + wait
    while True:
        code, _ = run_timed(["docker", "info"], 20)
        if code == 0:
            return True, "Docker daemon reachable"
        if time.monotonic() >= deadline or not sleep(5):
            return False, "cannot reach the Docker daemon (is docker.service running?)"


def storage_server(path):
    """(host, port) of the network share fstab mounts at path, or None for a local disk."""
    code, out = run_timed(["findmnt", "--fstab", "-n", "-o", "SOURCE,FSTYPE", "--target", path], 10)
    if code != 0 or not out.strip():
        return None
    source, _, fstype = out.strip().partition(" ")
    fstype = fstype.strip()
    if fstype.startswith("nfs") and ":" in source:
        return source.split(":", 1)[0], 2049
    if fstype == "cifs" and source.startswith("//"):
        return source[2:].split("/", 1)[0], 445
    return None


def check_server(path):
    server = storage_server(path)
    if server is None:
        return True, f"{path} is not a network share"
    host, port = server
    if tcp_open(host, port):
        return True, f"storage server {host} reachable"
    return False, f"storage server {host} unreachable on port {port}"


def storage_fstype(path):
    code, out = run_timed(["findmnt", "-n", "-o", "FSTYPE", "--mountpoint", path], 10)
    fstypes = [t for t in out.split() if t != "autofs"] if code == 0 else []
    return fstypes[-1] if fstypes else None


def check_mount(path):
    # Touch the path to trigger an x-systemd.automount. With automount,
    # `mountpoint -q` is true for the autofs placeholder alone, so confirm the
    # real filesystem with findmnt afterwards.
    code, _ = run_timed(["stat", "-L", path + "/."], 15)
    if code is None:
        return False, f"{path} hangs (stale network mount?)"
    fstype = storage_fstype(path)
    if not fstype:
        return False, f"{path} is not mounted — plug in / mount the external disk first"
    return True, f"{path} mounted ({fstype})"


def check_appdata(path):
    code, _ = run_timed(["test", "-d", path, "-a", "-w", path], 15)
    if code == 0:
        return True, f"{path} writable"
    if code is None:
        return False, f"{path} hangs"
    return False, f"{path} missing or not writable by {os.environ.get('USER', 'this user')}"


def check_root_env(root_env):
    if not os.path.isfile(os.path.join(ROOT_DIR, ".env")):
        return False, "root .env missing — run ./configure.sh"
    bad = [k for k in ("MEDIA_ROOT", "EXTERNAL_STORAGE") if not root_env.get(k) or "CHANGEME" in root_env[k]]
    bad += [k for k, v in root_env.items() if "CHANGEME" in v and k not in bad]
    if bad:
        return False, "root .env has unset values: " + ", ".join(bad)
    return True, "root .env configured"


def run_checks(root_env, quiet=False):
    """Run every requirement check in order; stop at the first failure."""
    storage = root_env.get("EXTERNAL_STORAGE", "")
    appdata = root_env.get("APPDATA_ROOT") or (storage + "/Storage" if storage else "")
    checks = [
        lambda: check_root_env(root_env),
        check_docker,
        lambda: check_server(storage),
        lambda: check_mount(storage),
        lambda: check_appdata(appdata),
    ]
    for check in checks:
        ok, msg = check()
        if not quiet or not ok:
            log("OK" if ok else "FAIL", msg)
        if not ok:
            return False, msg
    return True, ""


def storage_ok(root_env):
    storage = root_env["EXTERNAL_STORAGE"]
    for check in (check_server, check_mount):
        ok, msg = check(storage)
        if not ok:
            return False, msg
    return True, ""


# ── Commands ─────────────────────────────────────────────────────────────────
def cmd_check(_args):
    root_env, active, skipped = load_stacks()
    ok, _ = run_checks(root_env)
    for stack, why in skipped:
        log("SKIP", f"{stack.name} — {why}")
    log("", f"{len(active)} stack(s) would start.")
    return 0 if ok else 1


def cmd_status(_args):
    _root_env, active, skipped = load_stacks()
    for stack in active:
        items = stack.containers()
        if items is None:
            log("FAIL", f"{stack.name:15} docker compose ps failed")
            continue
        running = sum(1 for c in items if c.get("State") == "running")
        bad = stack.problems(items)
        tag = "OK" if not bad else "FAIL"
        detail = "" if not bad else "  (" + ", ".join(f"{s}: {r}" for s, r in bad) + ")"
        log(tag, f"{stack.name:15} {running}/{len(items)} running{detail}")
    for stack, why in skipped:
        log("SKIP", f"{stack.name:15} {why}")
    return 0


def wait_for_requirements(root_env):
    last = None
    while True:
        ok, msg = run_checks(root_env, quiet=last is not None)
        if ok:
            return True
        if msg != last:
            log("", f"    waiting — retrying every {REQUIREMENT_RETRY}s")
            last = msg
        if not sleep(REQUIREMENT_RETRY):
            return False


def heal(stack, now):
    """Bring a stack back up, with a restart budget per window."""
    bad = stack.problems()
    if not bad:
        if stack.paused_until is not None:
            log("OK", f"{stack.name} is healthy again")
            stack.paused_until = None
        stack.restarts.clear()
        return
    if stack.paused_until is not None:
        if now < stack.paused_until:
            return
        log("WARN", f"{stack.name} — still failing; trying again")
        stack.paused_until = None
        stack.restarts.clear()
    while stack.restarts and now - stack.restarts[0] > RESTART_WINDOW:
        stack.restarts.popleft()
    if len(stack.restarts) >= MAX_RESTARTS:
        log("FAIL", f"{stack.name} — {MAX_RESTARTS} restarts in {RESTART_WINDOW // 60} min; "
            f"pausing for {RESTART_WINDOW // 60} min (check: docker compose -f {stack.compose} logs)")
        stack.paused_until = now + RESTART_WINDOW
        return
    stack.restarts.append(now)
    log("WARN", f"{stack.name} — " + ", ".join(f"{s}: {r}" for s, r in bad) + "; restarting")
    if stack.up():
        unhealthy = [s for s, r in bad if r == "unhealthy"]
        if unhealthy:
            stack.restart_services(unhealthy)


def probe(host, port):
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/")
        status = conn.getresponse().status
        conn.close()
        return status
    except (OSError, http.client.HTTPException):
        return None


def run_probes(root_env, active, previous):
    host = root_env.get("SERVICE_HOST") or "127.0.0.1"
    names = {s.name for s in active}
    for stack_name, label, port in PROBES:
        if stack_name not in names:
            continue
        code = probe(host, port)
        ok = code in PROBE_OK
        if previous.get(label) != ok:
            if ok:
                log("OK", f"{label} answers on {host}:{port} (HTTP {code})")
            else:
                log("FAIL", f"{label} not answering on {host}:{port} ({'HTTP ' + str(code) if code else 'no response'})")
            previous[label] = ok


def cmd_run(args):
    root_env, active, skipped = load_stacks()
    log("", f"=== stack-guard: {len(active)} stack(s) in {ROOT_DIR} ===")
    for stack, why in skipped:
        log("SKIP", f"{stack.name} — {why}")

    if not wait_for_requirements(root_env):
        return 0

    log("", "=== Starting stacks ===")
    for stack in active:
        if stop_event.is_set():
            return 0
        if stack.up(pull=args.pull, dry_run=args.dry_run) and not args.dry_run:
            log("OK", f"{stack.name} up")
    if args.dry_run:
        return 0
    dependent = [s for s in active if s.uses_storage]
    remount_stubs(root_env, dependent)

    log("", f"=== Watching (every {WATCH_INTERVAL}s) ===")
    storage_lost, storage_fails = False, 0
    probe_state, next_probe = {}, time.monotonic() + 60
    while sleep(WATCH_INTERVAL):
        try:
            ok, msg = storage_ok(root_env)
            storage_fails = 0 if ok else storage_fails + 1
            # One missed check is a blip, not an outage: don't stop anything for it.
            if storage_fails >= STORAGE_FAILS and not storage_lost:
                log("FAIL", f"{msg} — stopping " + ", ".join(s.name for s in dependent))
                for stack in dependent:
                    stack.stop()
                storage_lost = True
            elif ok and storage_lost:
                log("OK", "storage is back — starting " + ", ".join(s.name for s in dependent))
                for stack in dependent:
                    stack.up()
                storage_lost = False
                continue

            # While storage is out (or flaky), keep healing everything that doesn't need it.
            now = time.monotonic()
            for stack in active:
                if stop_event.is_set():
                    break
                if ok or not stack.uses_storage:
                    heal(stack, now)
            if now >= next_probe:
                run_probes(root_env, [s for s in active if ok or not s.uses_storage], probe_state)
                next_probe = now + PROBE_INTERVAL
        except Exception as e:  # one bad pass must not take the watchdog down
            log("FAIL", f"watch pass failed: {e!r}")
    log("", "stack-guard stopping (containers keep running)")
    return 0


def remount_stubs(root_env, dependent):
    """Restart stacks Docker auto-started before the share was mounted."""
    storage = root_env["EXTERNAL_STORAGE"]
    fstype = storage_fstype(storage)
    if not fstype:
        return
    for stack in dependent:
        stubs = stack.stub_mounts(storage, fstype)
        if stubs:
            log("WARN", f"{stack.name} started before {storage} was mounted ({', '.join(stubs)}); restarting")
            stack.restart()


def main():
    parser = argparse.ArgumentParser(description="Start the home lab stacks at boot and keep them running.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "check", "status"])
    parser.add_argument("--pull", action="store_true", help="pull images before the first start")
    parser.add_argument("--dry-run", action="store_true", help="check and show what would start; change nothing")
    args = parser.parse_args()

    if sys.platform != "linux":
        log("FAIL", "stack-guard.py is Linux-only (systemd, findmnt)")
        return 1

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop_event.set())

    return {"run": cmd_run, "check": cmd_check, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
