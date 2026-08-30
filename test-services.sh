#!/usr/bin/env bash
#
# test-services.sh — health-check every stack and report Tailscale connectivity.
# Runs on macOS and Linux.
#
# The probe target comes from SERVICE_HOST in the root .env (falling back to
# 127.0.0.1). Point it at your Tailscale IP or MagicDNS name to verify remote
# reachability rather than just local binding:
#
#   SERVICE_HOST=100.105.40.95 ./test-services.sh
#
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Read SERVICE_HOST from the root .env without sourcing it (a .env may contain
# characters the shell would try to interpret).
env_value() {
	[[ -f "${ROOT_DIR}/.env" ]] || return 0
	awk -F= -v k="$1" '$1==k { sub(/^[^=]*=/,""); gsub(/^["'"'"']|["'"'"']$/,""); v=$0 } END { print v }' "${ROOT_DIR}/.env"
}

SERVICE_HOST="${SERVICE_HOST:-$(env_value SERVICE_HOST)}"
SERVICE_HOST="${SERVICE_HOST:-127.0.0.1}"

echo "=== Container health ==="
if docker info >/dev/null 2>&1; then
	docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
else
	echo "  [FAIL] cannot reach the Docker daemon"
fi
echo

echo "=== Service reachability (via ${SERVICE_HOST}) ==="

fails=0

check() {
	local name="$1" port="$2"
	local url="http://${SERVICE_HOST}:${port}"
	local code
	code=$(curl -s --connect-timeout 5 "${url}" -o /dev/null -w "%{http_code}")
	# A login redirect or a 401 still proves the service is listening.
	if [[ ${code} =~ ^(200|301|302|400|401|403)$ ]]; then
		printf '  [OK]   %-15s %-5s HTTP %s\n' "${name}" "${port}" "${code}"
	else
		printf '  [FAIL] %-15s %-5s HTTP %s (expected 2xx/3xx/4xx-auth)\n' "${name}" "${port}" "${code}"
		fails=$((fails + 1))
	fi
}

check "portainer" 9000
check "jellyfin" 8096
check "immich" 2283
check "homeassistant" 8123
check "papra" 1221
check "audiobookshelf" 13378
check "obsidian" 3000
check "coolify" 8000
echo

echo "=== Tailscale ==="
if ! command -v tailscale >/dev/null 2>&1; then
	echo "  [SKIP] tailscale is not installed — remote access checks skipped"
	echo "         macOS: the Mac App Store / brew build; Linux: see SETUP.md"
elif ! tailscale status >/dev/null 2>&1; then
	echo "  [SKIP] tailscale is installed but not connected ('tailscale up')"
else
	tailscale status
	echo
	echo "=== Direct P2P check (a relay means no direct connection) ==="
	if command -v python3 >/dev/null 2>&1; then
		tailscale status --json 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
for peer in d.get('Peer', {}).values():
    relay  = peer.get('Relay') or ''
    direct = peer.get('CurAddr') or ''
    name   = peer.get('HostName', '?')
    if direct:
        print(f'  [DIRECT] {name} — {direct}')
    elif relay:
        print(f'  [RELAY]  {name} — via DERP/{relay}  ← fix: forward UDP 41641 on the router')
    else:
        print(f'  [OFFLINE] {name}')
"
	else
		echo "  [SKIP] python3 not found — read the 'relay=' / 'direct=' columns above by hand"
	fi
fi
echo

if ((fails)); then
	echo "${fails} service(s) unreachable on ${SERVICE_HOST}."
	echo "If they work on 127.0.0.1 but not on your Tailscale address, see"
	echo "PLAN.md § Troubleshooting: Services Not Reachable from Tailscale Peers."
	exit 1
fi

echo "All services reachable on ${SERVICE_HOST}."
