# Servers — Docker Home Lab

- **[SETUP.md](./SETUP.md)** — step-by-step guide to bring the whole lab up from scratch. Start here on a fresh machine.
- **[PLAN.md](./PLAN.md)** — operator reference: services, ports, storage layout, secrets, and gotchas.
- **[REQUIREMENTS.md](./REQUIREMENTS.md)** — approximate CPU, RAM, and disk needed to run the whole lab.

## `restart-all.sh`

Pulls the latest Docker images and recreates all home lab services in one shot.

### Usage

```bash
./restart-all.sh
```

Run from anywhere — the script resolves its own directory automatically.

### What it does

For each service it:

1. Pulls the latest image (`docker compose pull`)
2. Recreates containers with the new image (`docker compose up -d --remove-orphans`)

Services are restarted in this order:

| #   | Service        | Port        |
| --- | -------------- | ----------- |
| 1   | audiobookshelf | 13378       |
| 2   | coolify        | 8000        |
| 3   | papra-doc      | 1221        |
| 4   | home-assistant | 8123        |
| 5   | jellyfin       | 8096        |
| 6   | immich-photos  | 2283        |
| 7   | portainer      | 9000        |
| 8   | obsidian-brain | 3000 / 3001 |

If a service directory has no `docker-compose.yml` / `docker-compose.yaml`, it is skipped with a `[SKIP]` message.

When every service is done, the script runs `./test-services.sh`, which health-checks each one and reports Tailscale peer connectivity.

### Requirements

- Docker with the `compose` plugin (`docker compose`)
- Script must be executable: `chmod +x restart-all.sh`

## Environment variables

- <ROOT_USERNAME>: YOUR USER
- <EXTERNAL_STORAGE>: your mounted external storage
