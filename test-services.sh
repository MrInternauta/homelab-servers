#!/bin/bash
set -uo pipefail

TS_IP="100.105.40.95"

echo "=== Container health ==="
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo

echo "=== Service reachability (via Tailscale IP $TS_IP) ==="

check() {
  local name="$1" url="$2"
  local code
  code=$(curl -s --connect-timeout 5 "$url" -o /dev/null -w "%{http_code}")
  if [[ "$code" =~ ^(200|301|302|400|401|403)$ ]]; then
    echo "  [OK]   $name — HTTP $code"
  else
    echo "  [FAIL] $name — HTTP $code (expected 2xx/3xx)"
  fi
}

check "portainer"       "http://$TS_IP:9000"
check "jellyfin"        "http://$TS_IP:8096"
check "immich"          "http://$TS_IP:2283"
check "homeassistant"   "http://$TS_IP:8123"
check "papra"           "http://$TS_IP:1221"
check "audiobookshelf"  "http://$TS_IP:13378"
check "obsidian"        "http://$TS_IP:3000"
check "coolify"         "http://$TS_IP:8000"
echo

echo "=== Tailscale peer connectivity ==="
tailscale status
echo

echo "=== Direct P2P check (relay= means no direct connection — see PLAN.md Troubleshooting) ==="
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
        print(f'  [RELAY]  {name} — via DERP/{relay}  ← fix: forward UDP 41641 on router')
    else:
        print(f'  [OFFLINE] {name}')
"
echo
