# Home Lab Plan & Context

Self-hosted Docker home lab. Each service is an independent `docker compose` stack.
**Runs on macOS and on Linux** from the same files — host-specific values live in `.env`, never in
the compose files. Timezone default: `America/Mexico_City`.

> Companion docs: **[SETUP.md](./SETUP.md)** (step-by-step bring-up),
> **[DOCKER-INSTALL.md](./DOCKER-INSTALL.md)** (installing Docker on either OS),
> **[REQUIREMENTS.md](./REQUIREMENTS.md)** (hardware sizing),
> `README.md`, `configure.sh` (host config), `restart-all.sh` (bulk pull + recreate),
> `test-services.sh` (health checks).

## Configuration model

There are no placeholders to substitute. Every host-specific value is a **compose variable** read
from the `.env` file sitting next to each `docker-compose.yml`:

| Variable           | Meaning                                                   | 🍎 macOS example                | 🐧 Linux example |
| ------------------ | --------------------------------------------------------- | ------------------------------- | ---------------- |
| `MEDIA_ROOT`       | Parent of `Audio/ Videos/ Images/ Documents/`, local disk | `/Users/felipe`                 | `/home/felipe`   |
| `EXTERNAL_STORAGE` | Mount point of the NAS / external disk, **full path**     | `/Volumes/NAS`                  | `/mnt/nas`       |
| `PUID` / `PGID`    | Host uid/gid the containers write as                      | `501` / `20`                    | `1000` / `1000`  |
| `TZ`               | Timezone for every container                              | `America/Mexico_City`           | same             |
| `COOLIFY_STORAGE`  | Where all Coolify state lives (coolify only)              | `/Volumes/NAS/Storage/coolify`  | `/data/coolify`  |
| `SERVICE_HOST`     | Address `test-services.sh` probes (root `.env` only)      | `127.0.0.1` or the Tailscale IP | same             |

The **root `.env` is the source of truth.** `./configure.sh` detects the OS, fills in defaults, and
fans those values out into each service's `.env`, generating any missing secret along the way. Run
it again after moving your storage.

Path variables are declared as `${VAR:?message}`, so a missing value **fails the command with an
explanation** rather than silently mounting an empty directory:

```text
required variable MEDIA_ROOT is missing a value: set MEDIA_ROOT in .env — run ./configure.sh
```

## Overview

| Service        | Directory         | Port(s)          | Image                                          | Purpose                                 |
| -------------- | ----------------- | ---------------- | ---------------------------------------------- | --------------------------------------- |
| Audiobookshelf | `audiobookshelf/` | 13378            | `ghcr.io/advplyr/audiobookshelf`               | Audiobook & podcast server              |
| Papra          | `papra-doc/`      | 1221             | `ghcr.io/papra-hq/papra`                       | Document management                     |
| Home Assistant | `home-assistant/` | 8123             | `ghcr.io/home-assistant/home-assistant:stable` | Home automation (privileged, NET_ADMIN) |
| Jellyfin       | `jellyfin/`       | 8096             | `lscr.io/linuxserver/jellyfin`                 | Media server (movies, videos)           |
| Immich         | `immich-photos/`  | 2283             | `ghcr.io/immich-app/immich-server`             | Photo library (4 containers)            |
| Portainer      | `portainer/`      | 9000             | `portainer/portainer-ce:lts`                   | Docker management UI                    |
| Obsidian       | `obsidian-brain/` | 3000 / 3001      | `lscr.io/linuxserver/obsidian`                 | Obsidian vault (web GUI, Chromium)      |
| Coolify        | `coolify/`        | 8000, 6001, 6002 | `coollabsio/coolify`                           | Self-hosted PaaS (4 containers)         |

**14 containers** across 8 stacks.

## Service Details

- **audiobookshelf/** — Port 13378 (`13378:80`). The image ignores `PUID`/`PGID`, so it takes a
  plain `user: "${PUID}:${PGID}"` directive instead. Config/metadata in `./config`, `./metadata`.
- **papra-doc/** — Port 1221. Runs as `user: "${PUID}:${PGID}"`. Needs `AUTH_SECRET` from its
  `.env`. Its data folder is `${EXTERNAL_STORAGE}/Documents`.
- **home-assistant/** — Port 8123. `privileged: true` plus `NET_ADMIN` + `NET_RAW`.
  🐧 On Linux, uncomment `network_mode: host` for working mDNS/SSDP discovery, and the `devices:`
  block for a Zigbee/Z-Wave dongle. 🍎 On macOS neither helps — the Docker VM is NAT'd off the LAN.
- **jellyfin/** — Port 8096 (8920 HTTPS commented out). Config in `./config`, transcode cache in
  `./cache`. 🐧 Linux can pass `/dev/dri` through for VAAPI/QSV hardware transcoding (commented
  block + `RENDER_GID` in its `.env`), or an NVIDIA GPU via the `deploy:` block. 🍎 macOS is
  CPU-only, always.
- **immich-photos/** — 4 containers on port 2283: `immich_server`, `immich_ml`, `immich_redis`
  (valkey 9), `immich_db` (Immich's pinned pgvector Postgres 14 image — do not swap it for stock
  postgres). **DB data and ML cache are repo-local** (`./db-data`, `./ml-cache`), deliberately: a
  network round-trip would make Postgres crawl. 🐧 Linux with an NVIDIA GPU can use the `-cuda` ML
  image tag.
- **portainer/** — Port 9000, mounts the Docker socket, data in the named volume `portainer_data`.
  🐧 On Linux your user must be in the `docker` group for that mount to be usable. Alternate
  `compose-with-tsdproxy.yaml` adds `tsdproxy.*` labels for a Tailscale proxy sidecar (the sidecar
  itself is not in this repo).
- **obsidian-brain/** — LinuxServer Obsidian on 3000 (HTTP GUI) / 3001 (HTTPS). Chromium-based, so
  `seccomp:unconfined` and `shm_size: 1gb`. Config & vaults in `./obsidian/config`. Runs as the
  shared `PUID`/`PGID`, so the vault stays editable from the host on both OSes.
- **coolify/** — 4 containers: `coolify` UI (`${APP_PORT:-8000}` → 8080), `coolify-db` (Postgres
  15), `coolify-redis` (Redis 7), `coolify-realtime` (soketi, 6001/6002), all on a dedicated
  `coolify` bridge network. The UI has `depends_on: service_healthy` for all three, so it will not
  start until they pass their healthchecks. All state lives under `COOLIFY_STORAGE`.
  🐧 **Linux is where Coolify actually works** — uncomment the Docker socket mount and it can
  deploy to the host. 🍎 On macOS it runs but cannot manage the Mac; it is a dashboard only.

## Storage Layout

`./` is relative to the service directory inside this repo.

| Service        | Host path                                                                         | Container path                            | Mode    |
| -------------- | --------------------------------------------------------------------------------- | ----------------------------------------- | ------- |
| audiobookshelf | `./config`, `./metadata`                                                          | `/config`, `/metadata`                    | rw      |
| audiobookshelf | `${MEDIA_ROOT}/Audio`                                                             | `/audiobooks`                             | rw      |
| audiobookshelf | `${MEDIA_ROOT}/Documents`                                                         | `/books`                                  | rw      |
| audiobookshelf | `${EXTERNAL_STORAGE}/Audio`                                                       | `/audiobooks-external`                    | rw      |
| audiobookshelf | `${EXTERNAL_STORAGE}/Documents`                                                   | `/books-external`                         | rw      |
| jellyfin       | `./config`, `./cache`                                                             | `/config`, `/cache`                       | rw      |
| jellyfin       | `${MEDIA_ROOT}/Videos`                                                            | `/data/videos`                            | rw      |
| jellyfin       | `${EXTERNAL_STORAGE}/Videos`                                                      | `/data/videos-external`                   | rw      |
| immich         | `${EXTERNAL_STORAGE}/Images`                                                      | `/mnt/external-data`                      | rw      |
| immich         | `${MEDIA_ROOT}/Images`                                                            | `/mnt/external-library`                   | **ro**  |
| immich         | `./db-data`, `./ml-cache`                                                         | postgres data, `/cache`                   | rw      |
| papra          | `${EXTERNAL_STORAGE}/Documents`                                                   | `/app/app-data`                           | rw      |
| papra          | `${MEDIA_ROOT}/Documents`                                                         | `/data/documents`                         | rw      |
| home-assistant | `./config`, `./run/dbus`                                                          | `/config`, `/run/dbus`                    | rw / ro |
| obsidian       | `./obsidian/config`                                                               | `/config`                                 | rw      |
| coolify        | `${COOLIFY_STORAGE}/{ssh,applications,databases,services,backups,postgres,redis}` | various under `/var/www/html/storage/app` | rw      |
| portainer      | `/var/run/docker.sock`, `portainer_data`                                          | socket, `/data`                           | rw      |

**Summary:** local media lives under `${MEDIA_ROOT}/{Audio,Videos,Images,Documents}`; the external
volume mirrors those four and additionally holds all Coolify state under `${COOLIFY_STORAGE}`.
Immich's database is _not_ on the external volume.

🐧 On Linux, `${COOLIFY_STORAGE}` is best pointed at a **local** disk (e.g. `/data/coolify`) rather
than the NAS — Postgres over NFS/SMB is slow and prone to corruption.

## Environment & Secrets

Every service reads the `.env` next to its compose file, and every service ships a committed
`.env.example` with the same keys and **no** real values. `./configure.sh` creates all of them.

| Service           | Keys it declares                                                                                                 | Notes                                           |
| ----------------- | ---------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| _(root)_ `.env`   | `TZ`, `PUID`, `PGID`, `MEDIA_ROOT`, `EXTERNAL_STORAGE`, `SERVICE_HOST`                                           | Source of truth; `configure.sh` fans it out     |
| `audiobookshelf/` | `TZ`, `PUID`, `PGID`, `MEDIA_ROOT`, `EXTERNAL_STORAGE`                                                           | No secrets                                      |
| `jellyfin/`       | `TZ`, `PUID`, `PGID`, `MEDIA_ROOT`, `EXTERNAL_STORAGE`, _(opt)_ `RENDER_GID`                                     | No secrets; `RENDER_GID` is Linux-only          |
| `home-assistant/` | `TZ`                                                                                                             | No secrets — HA keeps its own inside `./config` |
| `obsidian-brain/` | `TZ`, `PUID`, `PGID`                                                                                             | No secrets                                      |
| `portainer/`      | `TZ`                                                                                                             | No secrets — admin account lives in the volume  |
| `papra-doc/`      | `AUTH_SECRET`, `TZ`, `PUID`, `PGID`, `MEDIA_ROOT`, `EXTERNAL_STORAGE`                                            | Also loaded into the container via `env_file:`  |
| `immich-photos/`  | `IMMICH_VERSION`, `DB_USERNAME`, `DB_PASSWORD`, `DB_DATABASE_NAME`, `TZ`, `MEDIA_ROOT`, `EXTERNAL_STORAGE`       | Loaded via `env_file:`                          |
| `coolify/`        | `APP_*`, `DB_*`, `REDIS_PASSWORD`, `PUSHER_APP_*`, `SOKETI_*`, `COOLIFY_STORAGE`, `REGISTRY_URL`, `LATEST_IMAGE` | Loaded via `env_file:`                          |

**Set up everything at once:**

```bash
cp .env.example .env && $EDITOR .env && ./configure.sh
```

**Or one service by hand:**

```bash
cp <service-dir>/.env.example <service-dir>/.env
$EDITOR <service-dir>/.env
```

Generate strong values with `openssl rand -hex 32` (or `-hex 24` / `-base64 32` as noted in each
template) — `configure.sh` does this for you and never overwrites a value you already set.

The root `.gitignore` ignores every real `.env` / `.env.*` but keeps `.env.example` (and
`*.example`) tracked, and excludes the runtime data directories the bind mounts create.

## Network / Tailscale

The host is reachable over Tailscale from any device on the tailnet:

```text
http://<machine>.<tailnet>.ts.net:<port>
```

`test-services.sh` probes `SERVICE_HOST` from the root `.env` (default `127.0.0.1`). Set it to your
Tailscale IP or MagicDNS name to test remote reachability instead of just local binding.

🐧 **Linux firewalls.** macOS ships with its firewall off by default; most Linux distros do not.
Allow the tailnet interface rather than opening ports to the world:

```bash
sudo ufw allow in on tailscale0                                    # Debian/Ubuntu
sudo firewall-cmd --permanent --zone=trusted --add-interface=tailscale0 && sudo firewall-cmd --reload   # Fedora/RHEL
```

Portainer has an alternate compose file `portainer/compose-with-tsdproxy.yaml` that adds
`tsdproxy.enable` / `tsdproxy.ephemeral` labels for a Tailscale proxy sidecar.

### Port map

| Port  | Service                    |
| ----- | -------------------------- |
| 1221  | Papra                      |
| 2283  | Immich                     |
| 3000  | Obsidian (HTTP GUI)        |
| 3001  | Obsidian (HTTPS GUI)       |
| 6001  | Coolify realtime (soketi)  |
| 6002  | Coolify realtime (metrics) |
| 8000  | Coolify UI                 |
| 8096  | Jellyfin                   |
| 8123  | Home Assistant             |
| 9000  | Portainer                  |
| 13378 | Audiobookshelf             |

## Common Tasks

**Configure or re-configure the host** (after a fresh clone, or after moving storage):

```bash
./configure.sh              # add --dry-run to see what it would change
```

**Restart all services** (pull latest images + recreate containers, then health checks):

```bash
./restart-all.sh            # --no-pull to skip pulling, --no-test to skip the health check
```

It iterates `audiobookshelf → coolify → papra-doc → home-assistant → jellyfin → immich-photos →
portainer → obsidian-brain`, skips any directory with no compose file or no `.env`, finishes by
invoking `test-services.sh`, and exits non-zero if any stack failed.

**Health-check only:**

```bash
./test-services.sh
SERVICE_HOST=100.105.40.95 ./test-services.sh    # check over Tailscale instead of localhost
```

Prints `docker ps`, curls each service, then reports Tailscale peer connectivity and whether peers
are DIRECT or on a DERP relay. Skips the Tailscale section cleanly if it is not installed.

**Restart a single service:**

```bash
docker compose -f <service-dir>/docker-compose.yml pull && \
docker compose -f <service-dir>/docker-compose.yml up -d --remove-orphans
```

**Check running containers:** `docker ps`

**View logs for a service:** `docker compose -f <service-dir>/docker-compose.yml logs -f`

## Operating Notes / Gotchas

- **The external volume must be mounted first.** `${EXTERNAL_STORAGE}` is a bind-mount source for
  audiobookshelf, jellyfin, immich, papra, and all of Coolify. If it is not mounted, Docker creates
  an empty directory there and the containers start against empty storage — worst for Coolify,
  whose Postgres would initialise a brand-new empty database. `configure.sh` checks and warns;
  🍎 verify with `mount | grep`, 🐧 with `mountpoint`.
- **`configure.sh` is idempotent and non-destructive.** It never overwrites a secret that already
  has a value. Re-run it whenever the root `.env` changes.
- **`PUID`/`PGID` differ by OS** — macOS's first user is `501:20` (`staff`), Linux's is usually
  `1000:1000`. They come from `id -u` / `id -g` via `configure.sh`. Get them wrong and every file
  the containers write is owned by a user that does not exist on the host.
- 🐧 **Linux firewall and the `docker` group** are the two things macOS does not make you think
  about. `sudo usermod -aG docker $USER` and allow `tailscale0`.
- 🐧 **`sudo systemctl enable docker`** — `restart: unless-stopped` is meaningless if the daemon
  never starts at boot.
- `immich-photos` upgrades may require **DB migrations** — watch `immich_db` logs after a pull.
  Pin `IMMICH_VERSION` in its `.env` if you want to control when that happens.
- `coolify`'s UI waits on Postgres/Redis/soketi healthchecks; slow storage makes first start take a
  while. Check `docker compose -f coolify/docker-compose.yml ps` before assuming it failed.
- `home-assistant` runs privileged with `NET_ADMIN`/`NET_RAW` — treat its config directory as
  security-sensitive.
- `restart-all.sh` is the source of truth for which services exist and in what order they restart;
  the tables in `README.md` and here are copies of it and can drift.
- When helping with any service, **check its `docker-compose.yml` and `.env.example` first**; use
  `restart-all.sh` for bulk updates.

## Rationale

Home automation, media streaming, photo management, document archiving, and an app platform — all
self-hosted, with local media on the internal disk and bulk/Coolify storage on the external volume.
The lab started on a Mac mini; it now runs unchanged on a Linux server, which is the better host
for it (GPU transcoding, real device discovery, a working Coolify). See
[REQUIREMENTS.md § Platform differences](./REQUIREMENTS.md#platform-differences).

---

## Troubleshooting: Services Not Reachable from Tailscale Peers

**Investigated 2026-06-29 on the Mac mini.** All services were correctly configured host-side —
ports bound to `0.0.0.0`, the macOS Application Firewall disabled, Tailscale UDP 41641 listening.
Services responded correctly when accessed via the Tailscale IP locally.

### Root Cause: No Direct P2P — the peer used a DERP relay

```text
Peer: MacBook Pro | relay=den | direct=(none) | active=True
Peer: iPhone      | relay=dfw | direct=(none) | active=False
```

UDP hole-punching failed between the host and remote peers, so all traffic routed through
Tailscale's relay (DERP) servers. DERP connections are slower and can be flaky for persistent TCP
sessions to self-hosted services.

### Fix: Forward UDP 41641 on the Home Router

Add a port forwarding rule in your router admin panel:

| Field         | Value                                                              |
| ------------- | ------------------------------------------------------------------ |
| Protocol      | UDP                                                                |
| External port | 41641                                                              |
| Internal IP   | The host's LAN IP — 🍎 `ipconfig getifaddr en1` · 🐧 `hostname -I` |
| Internal port | 41641                                                              |

This lets Tailscale establish direct P2P connections instead of going through DERP.

### Verify After Fix

```bash
# Should show direct=<IP>:<port> instead of relay=...
tailscale status
```

`./test-services.sh` reports the same thing per peer as `[DIRECT]` or `[RELAY]`.

### Other Things Already Ruled Out

- Host firewall: **disabled** on the Mac — not blocking anything.
  🐧 On Linux this is the _first_ thing to check, not the last: `sudo ufw status`.
- Docker port bindings: all `0.0.0.0` — the Tailscale interface included
- Tailscale daemon: running, UDP 41641 listening on both IPv4 and IPv6
- Services: all healthy and responding via the Tailscale IP from localhost
