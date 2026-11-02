# Home Lab Plan & Context

Self-hosted Docker home lab. Each service is an independent `docker compose` stack.
**Runs on macOS and on Linux** from the same files — host-specific values live in `.env`, never in
the compose files. Timezone default: `America/Mexico_City`.

> Companion docs: **[SETUP.md](./SETUP.md)** (step-by-step bring-up),
> **[DOCKER-INSTALL.md](./DOCKER-INSTALL.md)** (installing Docker on either OS),
> **[REQUIREMENTS.md](./REQUIREMENTS.md)** (hardware sizing),
> `README.md`, `configure.sh` (host config), `restart-all.sh` (bulk pull + recreate),
> `test-services.sh` (health checks), `stack-guard.py` + `install-autostart.sh` (🐧 start at boot
> and keep running).

## Configuration model

There are no placeholders to substitute. Every host-specific value is a **compose variable** read
from the `.env` file sitting next to each `docker-compose.yml`:

| Variable           | Meaning                                                   | 🍎 macOS example                | 🐧 Linux example |
| ------------------ | --------------------------------------------------------- | ------------------------------- | ---------------- |
| `MEDIA_ROOT`       | Parent of `Audio/ Videos/ Images/ Documents/`, local disk | `/Users/felipe`                 | `/home/felipe`   |
| `EXTERNAL_STORAGE` | Mount point of the NAS / external disk, **full path**     | `/Volumes/NAS`                  | `/mnt/nas`       |
| `PUID` / `PGID`    | Host uid/gid the containers write as                      | `501` / `20`                    | `1000` / `1000`  |
| `TZ`               | Timezone for every container                              | `America/Mexico_City`           | same             |
| `APPDATA_ROOT`     | Container state (config, caches, DBs), one dir per app    | `/Volumes/NAS/Storage`          | `/mnt/nas/Storage` |
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
| AdGuard Home   | `adguard-home/`   | 53 (DNS), 3080   | `adguard/adguardhome`                          | Network-wide DNS ad blocker             |

**15 containers** across 9 stacks.

## Service Details

- **audiobookshelf/** — Port 13378 (`13378:80`). The image ignores `PUID`/`PGID`, so it takes a
  plain `user: "${PUID}:${PGID}"` directive instead. Config/metadata in `./config` and `./metadata` on the
  internal disk (its SQLite DB locks badly over NFS).
- **papra-doc/** — Port 1221. Runs as `user: "${PUID}:${PGID}"`. Needs `AUTH_SECRET` from its
  `.env`. SQLite DB in `/opt/papra/db`, documents in `/mnt/backup/papra/documents`, ingestion folder `/mnt/backup/papra/ingestion`
  (fixed Linux paths).
- **home-assistant/** — Port 8123. `privileged: true` plus `NET_ADMIN` + `NET_RAW`.
  🐧 On Linux, uncomment `network_mode: host` for working mDNS/SSDP discovery, and the `devices:`
  block for a Zigbee/Z-Wave dongle. 🍎 On macOS neither helps — the Docker VM is NAT'd off the LAN.
- **jellyfin/** — Port 8096 (8920 HTTPS commented out). Config and transcode cache in
  `./config` and `./cache` on the internal disk (SQLite over NFS locks badly). 🐧 Linux can pass `/dev/dri` through for VAAPI/QSV hardware transcoding (commented
  block + `RENDER_GID` in its `.env`), or an NVIDIA GPU via the `deploy:` block. 🍎 macOS is
  CPU-only, always.
- **immich-photos/** — 4 containers on port 2283: `immich_server`, `immich_ml`, `immich_redis`
  (valkey 9), `immich_db` (Immich's pinned pgvector Postgres 14 image — do not swap it for stock
  postgres). Uploads and ML cache live in `${APPDATA_ROOT}/immich/`; the Postgres data stays in
  `./db-data` on the internal disk — Postgres on exFAT, NFS or SMB is slow and corruption-prone. 🐧 Linux with an NVIDIA GPU can use the `-cuda` ML
  image tag.
- **portainer/** — Port 9000, mounts the Docker socket, data in the `portainer_data` named volume (it runs as
  root, and an NFS `APPDATA_ROOT` squashes root).
  🐧 On Linux your user must be in the `docker` group for that mount to be usable. Alternate
  `compose-with-tsdproxy.yaml` adds `tsdproxy.*` labels for a Tailscale proxy sidecar (the sidecar
  itself is not in this repo).
- **obsidian-brain/** — LinuxServer Obsidian on 3000 (HTTP GUI) / 3001 (HTTPS). Chromium-based, so
  `seccomp:unconfined` and `shm_size: 1gb`. Config & vaults in `./obsidian/config` on the internal disk. Runs as the
  shared `PUID`/`PGID`, so the vault stays editable from the host on both OSes.
- **coolify/** — 4 containers: `coolify` UI (`${APP_PORT:-8000}` → 8080), `coolify-db` (Postgres
  15), `coolify-redis` (Redis 7), `coolify-realtime` (soketi, 6001/6002), all on a dedicated
  `coolify` bridge network. The UI has `depends_on: service_healthy` for all three, so it will not
  start until they pass their healthchecks. All state lives under `COOLIFY_STORAGE`.
  🐧 **Linux is where Coolify actually works** — uncomment the Docker socket mount and it can
  deploy to the host. 🍎 On macOS it runs but cannot manage the Mac; it is a dashboard only.

- **adguard-home/** — DNS on port 53 (TCP + UDP), web UI on 3080 (`3080:3000` — the host's 3000
  is Obsidian, so keep the admin listener at 3000 in the setup wizard). Image tag pinned with
  `ADGUARD_VERSION` in its `.env`. State in `./work` and `./conf` on the internal disk, never on the
  NAS: DNS has to keep answering while the share is down, and since the stack mounts nothing from
  `EXTERNAL_STORAGE`, stack-guard leaves it running during a storage outage. DoT (853) and DoH
  (`8443:443`) are commented out until encryption is set up in its UI.
  🐧 Needs `systemd-resolved`'s stub listener turned off to free port 53 (SETUP.md § 5.9).
  Clients show up with their real IPs (only queries to `127.0.0.1` come from the bridge gateway).
  **Port 53 bypasses ufw** — restrict it with *Allowed clients*; see
  [Network-wide DNS / ad blocking](#network-wide-dns--ad-blocking).

## Storage Layout

Bulk state (Immich uploads and ML cache, Coolify) lives under `${APPDATA_ROOT}` (default
`${EXTERNAL_STORAGE}/Storage`). Anything with a SQLite/Postgres database, or that runs as root,
stays on the internal disk next to its compose file: on this host `APPDATA_ROOT` is NFS, where
SQLite locks badly and root is squashed.

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
| immich         | `${APPDATA_ROOT}/immich/{library,ml-cache}`                                       | `/data`, `/cache`                         | rw      |
| immich         | `./db-data`                                                                       | postgres data                             | rw      |
| papra          | `/opt/papra/db`                                                                   | `/app/app-data/db`                        | rw      |
| papra          | `/mnt/backup/papra/{documents,ingestion}`                                         | `/app/app-data/documents`, `/app/ingestion` | rw    |
| home-assistant | `./config`, `./run/dbus`                                                          | `/config`, `/run/dbus`                    | rw / ro |
| obsidian       | `./obsidian/config`                                                               | `/config`                                 | rw      |
| coolify        | `${COOLIFY_STORAGE}/{ssh,applications,databases,services,backups,postgres,redis}` | various under `/var/www/html/storage/app` | rw      |
| portainer      | `/var/run/docker.sock`, `portainer_data` volume                                   | socket, `/data`                           | rw      |
| adguard-home   | `./work`, `./conf`                                                                | `/opt/adguardhome/{work,conf}`            | rw      |

**Summary:** local media lives under `${MEDIA_ROOT}/{Audio,Videos,Images,Documents}`; the external
volume mirrors those four and additionally holds the bulk state under `${APPDATA_ROOT}`
(Coolify's under `${COOLIFY_STORAGE}`, which defaults to `${APPDATA_ROOT}/coolify`).
`restart-all.sh` and `stack-guard.py` refuse to start while `EXTERNAL_STORAGE` is unmounted.

🐧 On Linux, `${APPDATA_ROOT}` and `${COOLIFY_STORAGE}` are best pointed at a **local** disk
(e.g. `/data/homelab`, `/data/coolify`) when the external storage is a NAS — Postgres over NFS/SMB is slow and prone to corruption.

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
| `adguard-home/`   | `TZ`, `ADGUARD_VERSION`                                                                                          | No secrets — admin account lives in `./conf`    |
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
Allow the tailnet interface:

```bash
sudo ufw allow in on tailscale0                                    # Debian/Ubuntu
sudo firewall-cmd --permanent --zone=trusted --add-interface=tailscale0 && sudo firewall-cmd --reload   # Fedora/RHEL
```

**ufw/firewalld only cover services that run on the host itself** — SSH (22), rpcbind (111),
Tailscale (41641). Every port a container publishes goes through Docker's own iptables rules, which
run first, so all the service ports are open on **every** host address — LAN, tailnet, and a public
IPv6 one — whatever ufw says. What keeps them off the internet is the router; see
[Public exposure](#public-exposure).

Portainer has an alternate compose file `portainer/compose-with-tsdproxy.yaml` that adds
`tsdproxy.enable` / `tsdproxy.ephemeral` labels for a Tailscale proxy sidecar.

### Port map

| Port  | Service                    |
| ----- | -------------------------- |
| 53    | AdGuard Home (DNS)         |
| 1221  | Papra                      |
| 2283  | Immich                     |
| 3000  | Obsidian (HTTP GUI)        |
| 3001  | Obsidian (HTTPS GUI)       |
| 3080  | AdGuard Home (web UI)      |
| 6001  | Coolify realtime (soketi)  |
| 6002  | Coolify realtime (metrics) |
| 8000  | Coolify UI                 |
| 8096  | Jellyfin                   |
| 8123  | Home Assistant             |
| 9000  | Portainer                  |
| 13378 | Audiobookshelf             |

### Public exposure

Every port above is published on all host addresses (see Linux firewalls above), so the only
thing between the services and the internet is the router. **Checked 2026-11-02, behind the stock
Starlink router:**

| Path | Result | Why |
| ---- | ------ | --- |
| **IPv4** | Not reachable | Starlink CGNAT (shared public IPv4) and no port forwarding or UPnP; `tailscale netcheck` shows `PortMapping:` empty |
| **IPv6** | Not reachable | External scan ([IPscan](https://ipv6.chappell-family.com/ipv6tcptest/)) of the host's public `2605:59c8:…` address: all 91 tested ports **stealth** — UDP 53 + 18 others; TCP 22, 53, 111, 3000, 3080, 8123, 9000 + ~65 common ports. Those services are listening, so the router is dropping inbound IPv6 |

Not individually tested: 1221, 2283, 3001, 8096, 13378 (the scanner allows four custom ports).
Given the router dropped every port, including ones with a listener behind them, they are almost
certainly blocked the same way.

**Re-run the check** after changing the router, enabling Starlink bypass mode, or changing ISP. It
must run **on the server** (IPscan scans whoever calls it), and running it means accepting IPscan's
terms. Swap the four custom ports to cover others:

```bash
H=www66.chappell-family.co.uk
U="https://$H/cgi-bin6/ipscanfasttxt.cgi"
Q='includeexisting=1&customport0=9000'
Q="$Q&customport1=8123&customport2=3000"
Q="$Q&customport3=3080&termsaccepted=1"
curl -6 -s -m 120 "$U?$Q" | sed 's/<[^>]*>/ /g' | grep -oE 'Port [0-9]+(\[[0-9]\])? = [A-Z]+'
```

Anything other than `TCPSTEALTH`/`UDPSTEALTH` means that port is reachable from the internet. Then
drop inbound IPv6 for the service ports in Docker's `DOCKER-USER` chain (ufw rules won't apply), or
publish them on the LAN/tailnet addresses only.

## Network-wide DNS / ad blocking

AdGuard Home only blocks ads for devices that use it as their DNS server. Two places hand that out:

| Where                                        | Set                                                         | Covers                         |
| -------------------------------------------- | ----------------------------------------------------------- | ------------------------------ |
| Router → DHCP / LAN settings → DNS server    | The host's LAN IP (🐧 `hostname -I`), and **no** secondary  | Every device on the home LAN   |
| Tailscale admin console → DNS → Nameservers  | The host's Tailscale IP, with **Override local DNS** on     | Every tailnet device, anywhere |

- **No public secondary DNS.** Clients use the secondary whenever they like, not only as a
  fallback, so ads leak through it.
- **Keep MagicDNS working.** In Settings → DNS settings → Upstream DNS servers add
  `[/ts.net/]100.100.100.100`, so tailnet names are still resolved by Tailscale.
- **The server must not use itself for DNS.** With Override local DNS on, the host would also send
  its own lookups through AdGuard Home — and when that container is down it couldn't even pull an
  image to fix it. On the server only: `sudo tailscale set --accept-dns=false`.
- **Upstreams:** use encrypted ones, e.g. `https://dns.quad9.net/dns-query` and
  `https://cloudflare-dns.com/dns-query`.
- **Blocklists:** the default *AdGuard DNS filter* plus *OISD Big* (Filters → DNS blocklists →
  Add blocklist → Choose from the list) cover most ads and trackers with few false positives.
- **Access control — not the firewall.** Docker publishes port 53 through its own iptables rules,
  which run before ufw/firewalld, so a `ufw allow`/`deny` for 53 changes nothing: the port is open
  on every host address, including a public IPv6 one if the ISP hands those out. An open resolver
  on the internet gets abused for DDoS amplification. Restrict it in AdGuard Home → Settings → DNS
  settings → Access settings → **Allowed clients** (one per line; use your own subnets):

  ```text
  192.168.1.0/24
  fd99:acd9:1c4f:8::/64
  100.64.0.0/10
  fd7a:115c:a1e0::/48
  172.16.0.0/12
  ```

  In order: home LAN (IPv4), home LAN (IPv6 ULA), tailnet (IPv4), tailnet (IPv6), and the Docker
  bridges — queries sent to `127.0.0.1` arrive from the bridge gateway.
- **Single point of failure.** If this host is down, every client loses DNS — not just ad
  blocking. **Rollback:** set the router's DNS back to automatic and turn off the Tailscale
  nameserver override. A second AdGuard Home on another machine (synced with `adguardhome-sync`)
  removes the single point of failure.
- **A site breaks?** Query Log → find the blocked domain → *Unblock*. That adds an allowlist rule.

### Behind a Starlink router

The stock Starlink router does not let you change the DNS server it hands out — it always gives
clients itself (`192.168.1.1`, plus an IPv6 `fd…::1` address), and its DHCP can't be turned off.
So the router row in the table above isn't available. In order of preference:

| Option                               | How                                                                                                                  | Covers                                  |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| **Tailscale DNS** (recommended)      | The Tailscale row above. Override local DNS applies on the home Wi-Fi too                                            | Every device that runs Tailscale        |
| **Manual DNS per device**            | In the device's network settings: IPv4 DNS = host's LAN IP, IPv6 DNS = host's ULA (see below). Set **both**          | TVs, consoles, anything without Tailscale |
| **Own router behind Starlink**       | Starlink app → Router → *Bypass mode* (or the Starlink Ethernet adapter), then set DNS on your router as in the table above | The whole LAN — the only true network-wide option |

- **Set the IPv6 DNS too.** The Starlink router advertises its own IPv6 DNS server; a device with
  only the IPv4 DNS changed will keep asking Starlink over IPv6 and ads get through. Use the host's
  ULA (the `fd…` address), not its `2605:59c8:…` address — Starlink's public IPv6 prefix can change.
  🐧 Find it with `ip -6 addr show scope global | grep -o 'fd[0-9a-f:]*'`. AdGuard Home already
  listens on IPv6 (`[::]:53`).
- **Starlink hands out public IPv6**, so port 53 is published on a `2605:59c8:…` address too.
  The *Allowed clients* list above is what keeps that from being an open resolver.
- **Don't turn on AdGuard Home's DHCP server.** Starlink's DHCP keeps running, and two DHCP
  servers on one LAN hand out conflicting leases.
- **Bypass mode turns off Starlink's Wi-Fi** — your own router must provide it. Only worth it
  when the manual-DNS list gets long.

## Common Tasks

**Configure or re-configure the host** (after a fresh clone, or after moving storage):

```bash
./configure.sh              # add --dry-run to see what it would change
```

**Restart all services** (pull latest images + recreate containers, then health checks):

```bash
./restart-all.sh            # --no-pull to skip pulling, --no-test to skip the health check
```

It iterates `adguard-home → audiobookshelf → coolify → papra-doc → home-assistant → jellyfin → immich-photos →
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
  about. `sudo usermod -aG docker $USER` and allow `tailscale0`. ufw does **not** filter the
  container ports — Docker bypasses it; see [Public exposure](#public-exposure).
- 🐧 **`sudo systemctl enable docker`** — `restart: unless-stopped` is meaningless if the daemon
  never starts at boot.
- `immich-photos` upgrades may require **DB migrations** — watch `immich_db` logs after a pull.
  Pin `IMMICH_VERSION` in its `.env` if you want to control when that happens.
- `coolify`'s UI waits on Postgres/Redis/soketi healthchecks; slow storage makes first start take a
  while. Check `docker compose -f coolify/docker-compose.yml ps` before assuming it failed.
- **`adguard-home` and port 53** (🐧): `systemd-resolved` listens on `127.0.0.53:53`, so Docker
  can't publish `0.0.0.0:53` until its stub listener is off (SETUP.md § 5.9). A `bind: address
  already in use` on `adguard-home` means that step was skipped or undone.
- **DNS outages are network outages.** When AdGuard Home is down every client that uses it stops
  resolving names. Bring it back first, or roll back the router/Tailscale DNS (see
  [Network-wide DNS / ad blocking](#network-wide-dns--ad-blocking)).
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

> **Starlink:** this fix isn't available. Starlink puts you behind carrier-grade NAT (no public
> IPv4) and its router has no port forwarding. Tailscale still works, just more often over DERP;
> peers that also have IPv6 can usually connect directly over Starlink's native IPv6.

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
