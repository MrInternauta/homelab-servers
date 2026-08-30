# Home Lab Plan & Context

Self-hosted Docker home lab running on a **Mac mini**. Each service is an independent
`docker compose` stack. Timezone everywhere: `America/Mexico_City`.

> Companion docs: **[SETUP.md](./SETUP.md)** (step-by-step bring-up for humans),
> **[REQUIREMENTS.md](./REQUIREMENTS.md)** (hardware sizing),
> `README.md`, `restart-all.sh` (bulk pull + recreate), `test-services.sh` (health checks).

## Placeholders

The committed compose files are **templates**. Two placeholders appear verbatim inside them
and must be substituted with your real values before `docker compose` will run:

| Placeholder          | Meaning                                 | Example value   | Path prefix it completes        |
| -------------------- | --------------------------------------- | --------------- | ------------------------------- |
| `<ROOT_USERNAME>`    | Your macOS account (`whoami`)           | `feliperamirez` | `/Users/<ROOT_USERNAME>/…`      |
| `<EXTERNAL_STORAGE>` | Your mounted external / NAS volume name | `NAS`           | `/Volumes/<EXTERNAL_STORAGE>/…` |

Docker Compose does **not** expand `<...>` — it is not shell or `${VAR}` syntax. A stack started
without substitution will create a directory literally named `<ROOT_USERNAME>` instead of mounting
your data. See [SETUP.md](./SETUP.md#step-2--substitute-the-placeholders) for the substitution step.

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

## Service Details

- **audiobookshelf/** — Port 13378 (`13378:80`). No PUID/PGID (the image doesn't use them).
  Config/metadata in `./config` and `./metadata`.
- **papra-doc/** — Port 1221. Runs as `user: "${UID}:${GID}"`, so `UID`/`GID` must come from its
  `.env`. Needs `AUTH_SECRET` from the same file.
- **home-assistant/** — Port 8123. `privileged: true` plus `NET_ADMIN` + `NET_RAW`. Mounts
  `./run/dbus` read-only and `./config`. Host networking is *not* used — discovery protocols that
  need L2 broadcast may not work.
- **jellyfin/** — Port 8096 (8920 HTTPS is commented out). `PUID=501` / `PGID=20` (the standard
  macOS first-user / `staff` pair). Config in `./config`, transcode cache in `./cache`.
- **immich-photos/** — 4 containers on port 2283: `immich_server`, `immich_ml`,
  `immich_redis` (valkey 9), `immich_db` (Immich's pinned pgvector postgres 14 image).
  **DB data and ML cache are repo-local** (`./db-data`, `./ml-cache`), not on the NAS.
- **portainer/** — Port 9000, mounts the Docker socket, data in the named volume
  `portainer_data`. Alternate `compose-with-tsdproxy.yaml` adds `tsdproxy.*` labels for a
  Tailscale proxy sidecar (the sidecar itself is not in this repo).
- **obsidian-brain/** — LinuxServer Obsidian on 3000 (HTTP GUI) / 3001 (HTTPS). Chromium-based, so
  `seccomp:unconfined` and `shm_size: 1gb`. Config & vaults in `./obsidian/config`.
- **coolify/** — 4 containers: `coolify` UI (`${APP_PORT:-8000}` → 8080), `coolify-db` (postgres 15),
  `coolify-redis` (redis 7), `coolify-realtime` (soketi, 6001/6002). All on a dedicated `coolify`
  bridge network. The UI has `depends_on: service_healthy` for all three, so it will not start until
  they pass their healthchecks. **Its persistent storage is the only NAS-backed storage in the lab.**

## Storage Layout

Everything under `./` is relative to the service directory inside this repo.

| Service        | Host path                                | Container path            | Mode |
| -------------- | ---------------------------------------- | ------------------------- | ---- |
| audiobookshelf | `./config`, `./metadata`                 | `/config`, `/metadata`    | rw   |
| audiobookshelf | `/Users/<ROOT_USERNAME>/Audio`           | `/audiobooks`             | rw   |
| audiobookshelf | `/Users/<ROOT_USERNAME>/Documents`       | `/books`                  | rw   |
| audiobookshelf | `/Volumes/<EXTERNAL_STORAGE>/Audio`      | `/audiobooks-external`    | rw   |
| audiobookshelf | `/Volumes/<EXTERNAL_STORAGE>/Documents`  | `/books-external`         | rw   |
| jellyfin       | `./config`, `./cache`                    | `/config`, `/cache`       | rw   |
| jellyfin       | `/Users/<ROOT_USERNAME>/Videos`          | `/data/videos`            | rw   |
| jellyfin       | `/Volumes/<EXTERNAL_STORAGE>/Videos`     | `/data/videos-external`   | rw   |
| immich         | `/Volumes/<EXTERNAL_STORAGE>/Images`     | `/mnt/external-data`      | rw   |
| immich         | `/Users/<ROOT_USERNAME>/Images`          | `/mnt/external-library`   | **ro** |
| immich         | `./db-data`, `./ml-cache`                | postgres data, `/cache`   | rw   |
| papra          | `./`                                     | `/app/app-data`           | rw   |
| papra          | `/Volumes/<EXTERNAL_STORAGE>/Documents`  | `/app/app-data`           | rw   |
| papra          | `/Users/<ROOT_USERNAME>/Documents`       | `/data/documents`         | rw   |
| home-assistant | `./config`, `./run/dbus`                 | `/config`, `/run/dbus`    | rw / ro |
| obsidian       | `./obsidian/config`                      | `/config`                 | rw   |
| coolify        | `/Volumes/<EXTERNAL_STORAGE>/Storage/coolify/{ssh,applications,databases,services,backups,postgres,redis}` | various under `/var/www/html/storage/app` | rw |
| portainer      | `/var/run/docker.sock`, `portainer_data` | socket, `/data`           | rw   |

**Summary:** local media lives under `/Users/<ROOT_USERNAME>/{Audio,Videos,Images,Documents}`;
the NAS mirrors `Audio`, `Videos`, `Images`, `Documents` and additionally holds all Coolify state
under `/Volumes/<EXTERNAL_STORAGE>/Storage/coolify/`. Immich's database is *not* on the NAS.

## Environment & Secrets

Secrets are kept out of the compose files and live in per-service `.env` files (git-ignored).
Each such service ships a committed `.env.example` template with the same keys but **no** real
values — copy it to `.env` and fill it in before starting the stack.

| Service          | `.env` keys                                                                                                    | Notes                                           |
| ---------------- | -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| `papra-doc/`     | `AUTH_SECRET`, `UID`, `GID`                                                                                    | `AUTH_SECRET` moved out of `docker-compose.yml` |
| `immich-photos/` | `IMMICH_VERSION`, `DB_USERNAME`, `DB_PASSWORD`, `DB_DATABASE_NAME`                                             | Compose loads it via `env_file:`                |
| `coolify/`       | `APP_*`, `DB_*`, `REDIS_PASSWORD`, `PUSHER_APP_*`, `SOKETI_*`, `REGISTRY_URL`, `LATEST_IMAGE`                  | Compose loads it via `env_file:`                |

The other services (`audiobookshelf/`, `jellyfin/`, `home-assistant/`, `obsidian-brain/`,
`portainer/`) contain no secrets — only non-sensitive inline config (`TZ`, `PUID`/`PGID`) — so
they have no `.env` file.

**Set up a service's env from its template:**

```bash
cp <service-dir>/.env.example <service-dir>/.env
# then edit <service-dir>/.env and fill in the secrets
```

Generate strong values with `openssl rand -hex 32` (or `-hex 24` / `-base64 32` as noted in each template).

The root `.gitignore` ignores every real `.env` / `.env.*` but keeps `.env.example` (and `*.example`)
tracked, and excludes the runtime data directories the bind mounts create.

## Network / Tailscale

The Mac mini is reachable over Tailscale:

|                       | Value                                |
| --------------------- | ------------------------------------ |
| **MagicDNS hostname** | `<YOUR TAILSCALE ADDRESS>.ts.net` |
| **Tailscale IP**      | `100.105.40.95`                      |

All services are accessible remotely via `http://<YOUR TAILSCALE ADDRESS>.ts.net:<port>`
(or `http://100.105.40.95:<port>`). `test-services.sh` probes every service over the Tailscale IP.

Portainer has an alternate compose file `portainer/compose-with-tsdproxy.yaml` that adds
`tsdproxy.enable` / `tsdproxy.ephemeral` labels for a Tailscale proxy sidecar.

### Port map

| Port  | Service                     |
| ----- | --------------------------- |
| 1221  | Papra                       |
| 2283  | Immich                      |
| 3000  | Obsidian (HTTP GUI)         |
| 3001  | Obsidian (HTTPS GUI)        |
| 6001  | Coolify realtime (soketi)   |
| 6002  | Coolify realtime (metrics)  |
| 8000  | Coolify UI                  |
| 8096  | Jellyfin                    |
| 8123  | Home Assistant              |
| 9000  | Portainer                   |
| 13378 | Audiobookshelf              |

## Common Tasks

**Restart all services** (pull latest images + recreate containers, then run health checks):

```bash
./restart-all.sh
```

It iterates `audiobookshelf → coolify → papra-doc → home-assistant → jellyfin → immich-photos →
portainer → obsidian-brain`, skips any directory with no compose file, and finishes by invoking
`test-services.sh`.

**Health-check only:**

```bash
./test-services.sh
```

Prints `docker ps`, curls each service over the Tailscale IP, then reports Tailscale peer
connectivity and whether peers are DIRECT or on a DERP relay.

**Restart a single service:**

```bash
docker compose -f <service-dir>/docker-compose.yml pull && \
docker compose -f <service-dir>/docker-compose.yml up -d --remove-orphans
```

**Check running containers:** `docker ps`

**View logs for a service:** `docker compose -f <service-dir>/docker-compose.yml logs -f`

## Operating Notes / Gotchas

- **Placeholders are literal.** `<ROOT_USERNAME>` / `<EXTERNAL_STORAGE>` must be substituted before
  any stack starts, or Docker silently bind-mounts freshly created directories with those literal
  names. See [SETUP.md](./SETUP.md).
- **The NAS must be mounted first.** `/Volumes/<EXTERNAL_STORAGE>` is a bind-mount source for
  audiobookshelf, jellyfin, immich, papra, and all of coolify. If the volume is not mounted, Docker
  creates an empty directory under `/Volumes/` and the containers start against empty storage —
  worst for Coolify, whose postgres would initialize a brand-new empty database.
- **`papra-doc` mounts two host paths onto the same container path** (`./` and
  `/Volumes/<EXTERNAL_STORAGE>/Documents` both → `/app/app-data`). The later mount wins, so the
  repo-relative one is dead weight. Drop one of the two when you next touch that file.
- **`obsidian-brain` uses `PUID=1000` / `PGID=1000`**, while the rest of the lab uses the macOS
  pair `501` / `20`. Files it writes to `./obsidian/config` will be owned by a UID that doesn't
  exist on the host; align it to `501`/`20` if you need to edit the vault from macOS.
- `immich-photos` upgrades may require **DB migrations** — watch `immich_db` logs after a pull.
  Pin `IMMICH_VERSION` in its `.env` if you want to control when that happens.
- `coolify`'s UI waits on postgres/redis/soketi healthchecks; a slow NAS makes first start take a
  while. Check `docker compose -f coolify/docker-compose.yml ps` before assuming it failed.
- `home-assistant` runs privileged with `NET_ADMIN`/`NET_RAW` — treat its config directory as
  security-sensitive.
- `restart-all.sh` is the source of truth for which services exist and in what order they restart;
  the tables in `README.md` and here are copies of it and can drift.
- When helping with any service, **check its `docker-compose.yml` first**; use `restart-all.sh`
  for bulk updates.

## Rationale

Home automation, media streaming, photo management, document archiving, and an app platform — all
self-hosted on the Mac mini, with local media on the internal disk and bulk/Coolify storage on the NAS.

---

## Troubleshooting: Services Not Reachable from Tailscale Peers

**Investigated 2026-06-29.** All services are correctly configured on the Mac mini side — ports bound to `0.0.0.0`, macOS Application Firewall disabled, Tailscale UDP 41641 listening. Services respond correctly when accessed via `100.105.40.95` locally.

### Root Cause: No Direct P2P — MacBook Uses DERP Relay

```text
Peer: MacBook Pro | relay=den | direct=(none) | active=True
Peer: iPhone      | relay=dfw | direct=(none) | active=False
```

UDP hole-punching fails between the Mac mini and remote peers, so all traffic routes through Tailscale's relay (DERP) servers. DERP connections are slower and can be flaky for persistent TCP sessions to self-hosted services.

### Fix: Forward UDP 41641 on the Home Router

Add a port forwarding rule in your router admin panel:

| Field         | Value                                          |
| ------------- | ---------------------------------------------- |
| Protocol      | UDP                                            |
| External port | 41641                                          |
| Internal IP   | Mac mini LAN IP (run `ipconfig getifaddr en1`) |
| Internal port | 41641                                          |

This allows Tailscale to establish direct P2P connections instead of going through DERP.

### Verify After Fix

```bash
# Should show direct=<IP>:<port> instead of relay=...
tailscale status
```

`./test-services.sh` reports the same thing per peer as `[DIRECT]` or `[RELAY]`.

### Other Things Already Ruled Out

- macOS Application Firewall: **disabled** — not blocking anything
- Docker port bindings: all `0.0.0.0` — Tailscale interface included
- Tailscale daemon: running, UDP 41641 listening on both IPv4 and IPv6
- Services: all healthy and responding via Tailscale IP from localhost
