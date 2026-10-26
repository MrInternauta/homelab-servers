#!/usr/bin/env bash
#
# install-autostart.sh — run stack-guard.py at every boot as a systemd service.
# Linux (systemd) only. Run it as your normal user; it uses sudo for the unit file.
#
# Usage:
#   ./install-autostart.sh              # install (or update) and start the service
#   ./install-autostart.sh --uninstall  # stop, disable and remove it
#
set -euo pipefail

SERVERS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_NAME="homelab-stack-guard.service"
UNIT_PATH="/etc/systemd/system/${UNIT_NAME}"
RUN_USER="${SUDO_USER:-$(id -un)}"

UNINSTALL=0
for arg in "$@"; do
	case "${arg}" in
	--uninstall) UNINSTALL=1 ;;
	-h | --help)
		sed -n '2,8p' "${BASH_SOURCE[0]}"
		exit 0
		;;
	*)
		echo "Unknown option: ${arg}" >&2
		exit 2
		;;
	esac
done

# ── Preflight ────────────────────────────────────────────────────────────────
if [[ "$(uname -s)" != "Linux" ]] || ! command -v systemctl >/dev/null 2>&1; then
	echo "install-autostart.sh needs Linux with systemd." >&2
	exit 1
fi

if ((EUID != 0)) && ! command -v sudo >/dev/null 2>&1; then
	echo "this script needs root for ${UNIT_PATH}, and sudo is not installed." >&2
	exit 1
fi
SUDO=()
((EUID == 0)) || SUDO=(sudo)

if ((UNINSTALL)); then
	if [[ -f ${UNIT_PATH} ]]; then
		echo ">>> sudo is needed to remove ${UNIT_PATH}"
		"${SUDO[@]}" systemctl disable --now "${UNIT_NAME}" || true
		"${SUDO[@]}" rm -f "${UNIT_PATH}"
		"${SUDO[@]}" systemctl daemon-reload
		echo "    [OK] ${UNIT_NAME} removed (containers keep running)"
	else
		echo "    [SKIP] ${UNIT_NAME} is not installed"
	fi
	exit 0
fi

if [[ ${RUN_USER} == "root" ]]; then
	echo "run this as the user that owns the stacks, not as root." >&2
	exit 1
fi

missing=()
command -v python3 >/dev/null 2>&1 || missing+=("python3")
command -v findmnt >/dev/null 2>&1 || missing+=("util-linux")
if ((${#missing[@]})); then
	echo ">>> Installing ${missing[*]} (sudo)"
	"${SUDO[@]}" apt-get update -qq
	"${SUDO[@]}" apt-get install -y -qq "${missing[@]}"
fi

if ! command -v docker >/dev/null 2>&1; then
	echo "docker is not installed — see DOCKER-INSTALL.md" >&2
	exit 1
fi

if ! id -nG "${RUN_USER}" | tr ' ' '\n' | grep -qx docker; then
	echo "${RUN_USER} is not in the 'docker' group — see DOCKER-INSTALL.md" >&2
	exit 1
fi

chmod +x "${SERVERS_DIR}/stack-guard.py"

# ── Install ──────────────────────────────────────────────────────────────────
unit="$(
	cat <<EOF
[Unit]
Description=Home lab stack guard (start the docker compose stacks and keep them running)
Documentation=file://${SERVERS_DIR}/README.md
Wants=network-online.target docker.service
After=network-online.target docker.service remote-fs.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${SERVERS_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 ${SERVERS_DIR}/stack-guard.py run
Restart=on-failure
RestartSec=30
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF
)"

echo ">>> sudo is needed to write ${UNIT_PATH}"
printf '%s\n' "${unit}" | "${SUDO[@]}" tee "${UNIT_PATH}" >/dev/null
"${SUDO[@]}" systemctl daemon-reload
"${SUDO[@]}" systemctl enable "${UNIT_NAME}"
"${SUDO[@]}" systemctl restart "${UNIT_NAME}"

echo "    [OK] ${UNIT_NAME} installed and started as ${RUN_USER}"
echo
echo "Follow it with:  journalctl -u ${UNIT_NAME} -f"
