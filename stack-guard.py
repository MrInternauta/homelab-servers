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


def run_timed(cmd, timeout, capture=True):
    """Run cmd, never blocking past timeout + a few seconds.

    A command touching a dead `hard` NFS mount can sit in uninterruptible sleep
    and ignore SIGKILL, so don't wait for it forever after killing it.
    Returns (returncode or None on timeout, stdout).
    """
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
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
        self.compose = None
        for fname in ("docker-compose.yml", "docker-compose.yaml"):
            if os.path.isfile(os.path.join(self.dir, fname)):
                self.compose = os.path.join(self.dir, fname)
                break
        self.has_env = os.path.isfile(os.path.join(self.dir, ".env"))
        self.restarts = collections.deque()
        self.gave_up = False
        self.uses_storage = self._uses_storage(root_env)

    def _uses_storage(self, root_env):
        """True if the stack mounts anything from EXTERNAL_STORAGE / APPDATA_ROOT."""
        if not self.compose:
            return False
        with open(self.compose) as f:
            text = f.read()
        if "APPDATA_ROOT" in text or "EXTERNAL_STORAGE" in text:
            return True
        storage = root_env.get("EXTERNAL_STORAGE", "")
        if not storage:
            return False
        # e.g. coolify's COOLIFY_STORAGE may point onto the external disk. Only
        # look at variables the compose file uses: configure.sh copies the shared
        # paths into every .env whether or not the stack mounts them.
        used = set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", text))
        env = read_env(os.path.join(self.dir, ".env"))
        return any(v == storage or v.startswith(storage + "/") for k, v in env.items() if k in used)

    def compose_cmd(self, *args):
        return ["docker", "compose", "-f", self.compose, *args]

    def containers(self):
        """Containers of this stack as dicts, or None if compose failed."""
        code, out = run_timed(self.compose_cmd("ps", "-a", "--format", "json"), 30)
        if code != 0:
            return None
        out = out.strip()
        if not out:
            return []
        if out.startswith("["):
            return json.loads(out)
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    def problems(self):
        """List of (service, reason) for containers that are not up and healthy."""
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


def check_mount(path):
    # Touch the path to trigger an x-systemd.automount. With automount,
    # `mountpoint -q` is true for the autofs placeholder alone, so confirm the
    # real filesystem with findmnt afterwards.
    code, _ = run_timed(["stat", "-L", path + "/."], 15)
    if code is None:
        return False, f"{path} hangs (stale network mount?)"
    code, out = run_timed(["findmnt", "-n", "-o", "FSTYPE", "--mountpoint", path], 10)
    fstypes = [t for t in out.split() if t != "autofs"] if code == 0 else []
    if not fstypes:
        return False, f"{path} is not mounted — plug in / mount the external disk first"
    return True, f"{path} mounted ({fstypes[-1]})"


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
        bad = stack.problems()
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
        if stack.gave_up:
            log("OK", f"{stack.name} is healthy again")
            stack.gave_up = False
        return
    while stack.restarts and now - stack.restarts[0] > RESTART_WINDOW:
        stack.restarts.popleft()
    if len(stack.restarts) >= MAX_RESTARTS:
        if not stack.gave_up:
            log("FAIL", f"{stack.name} — {MAX_RESTARTS} restarts in {RESTART_WINDOW // 60} min; "
                f"leaving it alone (check: docker compose -f {stack.compose} logs)")
            stack.gave_up = True
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

    log("", f"=== Watching (every {WATCH_INTERVAL}s) ===")
    storage_lost = False
    probe_state, next_probe = {}, time.monotonic() + 60
    while sleep(WATCH_INTERVAL):
        ok, msg = storage_ok(root_env)
        dependent = [s for s in active if s.uses_storage]
        if not ok:
            if not storage_lost:
                log("FAIL", f"{msg} — stopping " + ", ".join(s.name for s in dependent))
                for stack in dependent:
                    stack.stop()
                storage_lost = True
            continue
        if storage_lost:
            log("OK", "storage is back — starting " + ", ".join(s.name for s in dependent))
            for stack in dependent:
                stack.up()
            storage_lost = False
            continue

        now = time.monotonic()
        for stack in active:
            if stop_event.is_set():
                break
            heal(stack, now)
        if now >= next_probe:
            run_probes(root_env, active, probe_state)
            next_probe = now + PROBE_INTERVAL
    log("", "stack-guard stopping (containers keep running)")
    return 0


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
