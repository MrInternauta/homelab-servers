# Servers — Docker Home Lab

Eight self-hosted `docker compose` stacks — media, photos, documents, home automation, and a PaaS —
that run from the same files on **macOS and Linux**.

```bash
git clone <this-repo> homelab-servers && cd homelab-servers
cp .env.example .env
$EDITOR .env          # set MEDIA_ROOT and EXTERNAL_STORAGE for your OS
./configure.sh        # fan those out, generate secrets, create directories
./restart-all.sh      # pull, start everything, health-check
```

## Docs

- **[DOCKER-INSTALL.md](./DOCKER-INSTALL.md)** — installing Docker Engine + the compose plugin on
  macOS (Docker Desktop or Colima) and on Linux (Debian/Ubuntu, Fedora/RHEL, Arch, openSUSE),
  including GPU and post-install setup. **Start here if `docker compose version` fails.**
- **[SETUP.md](./SETUP.md)** — step-by-step bring-up of the whole lab, with every macOS/Linux
  difference marked 🍎 / 🐧.
- **[PLAN.md](./PLAN.md)** — operator reference: services, ports, storage layout, secrets, gotchas.
- **[REQUIREMENTS.md](./REQUIREMENTS.md)** — CPU, RAM and disk needed, and how the two platforms
  differ in what they can actually do.
- **[docs/0.1.0.md](./docs/0.1.0.md)** — release notes. Read this if you are upgrading a checkout
  that still has `<ROOT_USERNAME>` in its compose files.

## Services

| #   | Service        | Directory         | Port(s)          |
| --- | -------------- | ----------------- | ---------------- |
| 1   | audiobookshelf | `audiobookshelf/` | 13378            |
| 2   | coolify        | `coolify/`        | 8000, 6001, 6002 |
| 3   | papra-doc      | `papra-doc/`      | 1221             |
| 4   | home-assistant | `home-assistant/` | 8123             |
| 5   | jellyfin       | `jellyfin/`       | 8096             |
| 6   | immich-photos  | `immich-photos/`  | 2283             |
| 7   | portainer      | `portainer/`      | 9000             |
| 8   | obsidian-brain | `obsidian-brain/` | 3000 / 3001      |

14 containers in total. The order above is the order `restart-all.sh` uses.

## Configuration

There is nothing to edit inside the compose files. Every host-specific value is a compose variable
read from the `.env` next to each `docker-compose.yml`:

| Variable           | Meaning                                         | 🍎 macOS              | 🐧 Linux        |
| ------------------ | ----------------------------------------------- | --------------------- | --------------- |
| `MEDIA_ROOT`       | Parent of `Audio/ Videos/ Images/ Documents/`   | `/Users/<you>`        | `/home/<you>`   |
| `EXTERNAL_STORAGE` | NAS / external disk mount point (**full path**) | `/Volumes/<Volume>`   | `/mnt/nas`      |
| `PUID` / `PGID`    | Host uid/gid the containers write as            | `501` / `20`          | `1000` / `1000` |
| `TZ`               | Timezone for every container                    | `America/Mexico_City` | same            |

The **root `.env` is the source of truth**; `configure.sh` fans it out into every service. A
missing value produces a clear error instead of a silently-empty mount.

## Scripts

### `configure.sh`

One-shot host configuration. Detects macOS vs Linux, creates the root and per-service `.env` files,
syncs the shared settings, generates any missing secret with `openssl`, and creates the host
directories the bind mounts need. Idempotent, and it never overwrites a secret you already set.

```bash
./configure.sh              # configure everything
./configure.sh --dry-run    # show what it would do, change nothing
```

Re-run it whenever you move your storage.

### `restart-all.sh`

Pulls the latest images and recreates every stack, in order, then runs `test-services.sh`.

```bash
./restart-all.sh            # pull + recreate + health-check
./restart-all.sh --no-pull  # recreate from the images already on disk
./restart-all.sh --no-test  # skip the health check
```

Skips any directory with no compose file (`[SKIP]`) or no `.env`, and exits non-zero if any stack
failed.

### `test-services.sh`

Health-checks every service and reports Tailscale peer connectivity (`[DIRECT]` / `[RELAY]`).

```bash
./test-services.sh
SERVICE_HOST=100.105.40.95 ./test-services.sh   # probe over Tailscale instead of localhost
```

The probe target comes from `SERVICE_HOST` in the root `.env`, default `127.0.0.1`. The Tailscale
section is skipped cleanly if Tailscale is not installed.

## Requirements

- Docker Engine with the **`docker compose` v2 plugin** — see
  [DOCKER-INSTALL.md](./DOCKER-INSTALL.md)
- `bash`, `curl`, `openssl` (all present by default on macOS and every mainstream Linux distro)
- The external storage volume mounted **before** starting any stack
- 🐧 Linux: your user in the `docker` group, and `sudo systemctl enable --now docker`
- 🍎 macOS: Docker Desktop running, with your home directory and `/Volumes` in its file-sharing list

Scripts must be executable: `chmod +x configure.sh restart-all.sh test-services.sh`
