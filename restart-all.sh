#!/bin/bash
set -euo pipefail

SERVERS_DIR="$(cd "$(dirname "$0")" && pwd)"

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

restart_service() {
  local name="$1"
  local dir="$SERVERS_DIR/$name"

  echo ">>> Restarting $name..."

  local compose_file=""
  if [[ -f "$dir/docker-compose.yml" ]]; then
    compose_file="docker-compose.yml"
  elif [[ -f "$dir/docker-compose.yaml" ]]; then
    compose_file="docker-compose.yaml"
  else
    echo "    [SKIP] No docker-compose file found in $dir"
    return
  fi

  docker compose -f "$dir/$compose_file" pull --quiet
  docker compose -f "$dir/$compose_file" up -d --remove-orphans
  echo "    [OK] $name restarted"
  echo
}

echo "=== Restarting all services ==="
echo

for service in "${SERVICES[@]}"; do
  restart_service "$service"
done

echo "=== All services restarted ==="
echo

bash "$SERVERS_DIR/test-services.sh"
