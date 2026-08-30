#!/usr/bin/env bash
#
# restart-all.sh — pull the latest images and recreate every stack, in order.
# Runs on macOS and Linux. Finishes by calling ./test-services.sh.
#
# Usage:
#   ./restart-all.sh              # pull + recreate everything, then health-check
#   ./restart-all.sh --no-pull    # recreate from the images already on disk
#   ./restart-all.sh --no-test    # skip the health check at the end
#
set -euo pipefail

SERVERS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DO_PULL=1
DO_TEST=1
for arg in "$@"; do
	case "${arg}" in
	--no-pull) DO_PULL=0 ;;
	--no-test) DO_TEST=0 ;;
	-h | --help)
		sed -n '2,10p' "${BASH_SOURCE[0]}"
		exit 0
		;;
	*)
		echo "Unknown option: ${arg}" >&2
		exit 2
		;;
	esac
done

SERVICES=(
	"audiobookshelf"
	"coolify"
	"papra-doc"
	"home-assistant"
	"jellyfin"
	"immich-photos"
	"portainer"
	"obsidian-brain"
)

# ── Preflight ────────────────────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
	echo "docker is not installed — see DOCKER-INSTALL.md" >&2
	exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
	echo "the 'docker compose' plugin is missing — see DOCKER-INSTALL.md" >&2
	exit 1
fi

HOST_OS="$(uname -s)"

if ! docker info >/dev/null 2>&1; then
	if [[ ${HOST_OS} == "Darwin" ]]; then
		echo "cannot reach the Docker daemon — is Docker Desktop (or Colima) running?" >&2
	else
		echo "cannot reach the Docker daemon — try 'sudo systemctl start docker', and" >&2
		echo "check that you are in the 'docker' group (see DOCKER-INSTALL.md)." >&2
	fi
	exit 1
fi

failed=()

restart_service() {
	local name="$1"
	local dir="${SERVERS_DIR}/${name}"

	echo ">>> Restarting ${name}..."

	local compose_file=""
	if [[ -f "${dir}/docker-compose.yml" ]]; then
		compose_file="docker-compose.yml"
	elif [[ -f "${dir}/docker-compose.yaml" ]]; then
		compose_file="docker-compose.yaml"
	else
		echo "    [SKIP] No docker-compose file found in ${dir}"
		return
	fi

	# Every stack reads its host paths and secrets from its own .env.
	if [[ -f "${dir}/.env.example" && ! -f "${dir}/.env" ]]; then
		echo "    [SKIP] ${name} has no .env — run ./configure.sh first"
		failed+=("${name} (no .env)")
		return
	fi

	if ((DO_PULL)); then
		if ! docker compose -f "${dir}/${compose_file}" pull --quiet; then
			echo "    [FAIL] ${name} — pull failed"
			failed+=("${name} (pull)")
			return
		fi
	fi

	if ! docker compose -f "${dir}/${compose_file}" up -d --remove-orphans; then
		echo "    [FAIL] ${name} — up failed"
		failed+=("${name} (up)")
		return
	fi

	echo "    [OK] ${name} restarted"
	echo
}

echo "=== Restarting all services (${HOST_OS}) ==="
echo

for service in "${SERVICES[@]}"; do
	restart_service "${service}"
done

if ((${#failed[@]})); then
	echo "=== Finished with problems ==="
	printf '  [FAIL] %s\n' "${failed[@]}"
	echo
else
	echo "=== All services restarted ==="
	echo
fi

if ((DO_TEST)); then
	bash "${SERVERS_DIR}/test-services.sh"
fi

((${#failed[@]} == 0))
