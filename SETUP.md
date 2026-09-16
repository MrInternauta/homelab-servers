# Setup Guide — Bringing the Whole Home Lab Up

A start-to-finish walkthrough for a fresh machine. **Works on macOS and on Linux** — every step
marks where the two differ with a 🍎 / 🐧 badge. Steps without a badge are identical on both.

For _what_ each service is and where its data lives, see **[PLAN.md](./PLAN.md)**.
For installing Docker itself, see **[DOCKER-INSTALL.md](./DOCKER-INSTALL.md)**.

**Time:** ~30–45 minutes, most of it image pulls.

---

## The short version

If you already know what you are doing:

```bash
git clone <this-repo> homelab-servers && cd homelab-servers
cp .env.example .env
$EDITOR .env                 # set MEDIA_ROOT and EXTERNAL_STORAGE for your OS
./configure.sh               # fans those out to every service, generates secrets, makes dirs
./restart-all.sh             # pull + start everything, then health-check
```

The rest of this document explains each of those, and what to check in between.

---

## Before you start

Two host paths drive the whole lab. Write yours down now:

| Variable           | What it is                                                          | 🍎 macOS                | 🐧 Linux                      |
| ------------------ | ------------------------------------------------------------------- | ----------------------- | ----------------------------- |
| `MEDIA_ROOT`       | Parent of `Audio/ Videos/ Images/ Documents/`, on the internal disk | `/Users/<you>`          | `/home/<you>` or `/srv/media` |
| `EXTERNAL_STORAGE` | Mount point of your NAS / external disk, **full path**              | `/Volumes/<VolumeName>` | `/mnt/<name>` or `/srv/nas`   |

Plus your user and group id — `configure.sh` reads these automatically, but it helps to know them:

```bash
id -u    # macOS: usually 501     Linux: usually 1000
id -g    # macOS: usually 20 (staff)   Linux: usually 1000
```

> **Upgrading from the old layout?** This repo used to ship compose files containing the literal
> text `<ROOT_USERNAME>` and `<EXTERNAL_STORAGE>` that you had to `sed` into place. That is gone.
> The compose files now use real `${VARIABLE}` interpolation fed from per-service `.env` files,
> so nothing needs editing and nothing shows up as modified in `git status`. See
> [Migrating from the placeholder layout](#migrating-from-the-placeholder-layout) at the end.

---

## Step 1 — Prerequisites

Install Docker Engine + the `docker compose` v2 plugin first:
**[DOCKER-INSTALL.md](./DOCKER-INSTALL.md)**.

```bash
docker --version
docker compose version    # must print v2.x — this repo uses the plugin, not docker-compose v1
docker info               # must succeed
```

🍎 **macOS:** `docker info` failing almost always means Docker Desktop (or Colima) is not running.
Also make sure **Settings → Resources → File sharing** lists your home directory and `/Volumes`,
or every bind mount in this repo will fail.

🐧 **Linux:** if `docker info` says _permission denied_, you are not in the `docker` group yet:

```bash
sudo usermod -aG docker "$USER" && newgrp docker
sudo systemctl enable --now docker      # also makes containers survive a reboot
```

Then clone the repo and make the scripts executable:

```bash
cd ~/Documents/projects/homelab-servers   # or wherever you cloned this
chmod +x configure.sh restart-all.sh test-services.sh
```

**Check:** `docker ps` prints a header row without error.

---

## Step 2 — Mount the external storage

`EXTERNAL_STORAGE` is a bind-mount source for audiobookshelf, jellyfin, immich, papra, and all of
Coolify. **It must be mounted before any stack starts.**

> **Why this matters:** if the volume is missing, Docker does not fail — it _creates an empty
> directory_ at that path and mounts that. Your libraries come up empty, and Coolify's Postgres
> initialises a brand-new blank database over the top of where your real one should be. Never
> start Coolify with the storage unmounted.

### 🍎 macOS

Mount it in Finder (⌘K for a network share), then:

```bash
ls /Volumes                      # your volume name appears here
mount | grep -i "<VolumeName>"   # confirms it is a real mount, not a stub directory
```

Add it to **System Settings → General → Login Items** so it remounts at boot.

### 🐧 Linux

Mount it yourself and make it permanent in `/etc/fstab` so a reboot does not silently detach your
storage:

```bash
sudo mkdir -p /mnt/nas

# Local disk — find the UUID first:
lsblk -f
echo 'UUID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx /mnt/nas ext4 defaults,nofail 0 2' \
  | sudo tee -a /etc/fstab

# NFS share:
# echo 'nas.local:/volume1/media /mnt/nas nfs defaults,nofail,_netdev 0 0' | sudo tee -a /etc/fstab

# SMB/CIFS share — put the credentials in a root-only file, never in fstab:
# printf 'username=me\npassword=secret\n' | sudo tee /etc/samba/nas-creds >/dev/null
# sudo chmod 600 /etc/samba/nas-creds
# echo "//nas.local/media /mnt/nas cifs credentials=/etc/samba/nas-creds,uid=$(id -u),gid=$(id -g),nofail,_netdev 0 0" \
#   | sudo tee -a /etc/fstab

sudo systemctl daemon-reload
sudo mount -a
```

`nofail` keeps a missing disk from blocking boot; `_netdev` makes network mounts wait for the
network. For CIFS, the `uid=`/`gid=` options matter — without them every file is owned by root and
the containers cannot write.

**Check (both):**

```bash
ls /mnt/nas                # or /Volumes/<VolumeName> — shows your content
mountpoint /mnt/nas        # Linux: "is a mountpoint"
```

---

## Step 3 — Configure the lab

One script does the whole thing. It detects your OS, fills in the defaults, creates every
service's `.env`, generates every secret, and creates the host directories:

```bash
cp .env.example .env
$EDITOR .env          # set MEDIA_ROOT and EXTERNAL_STORAGE (it refuses to run on CHANGEME)
./configure.sh
```

Prefer to look before it writes anything:

```bash
./configure.sh --dry-run
```

What it does, in order:

1. **Detects** macOS vs Linux, and your uid/gid.
2. **Creates the root `.env`** from `.env.example` if it does not exist, seeded with detected
   defaults.
3. **Creates each service's `.env`** from its `.env.example`.
4. **Syncs** `TZ`, `PUID`, `PGID`, `MEDIA_ROOT` and `EXTERNAL_STORAGE` from the root `.env` into
   every service `.env` that declares them. The root `.env` is the single source of truth; re-run
   the script any time you move your storage.
5. **Generates** any secret still empty — `AUTH_SECRET`, all the Coolify keys, both DB passwords —
   with `openssl`. It never overwrites a value you already set.
6. **Creates** `MEDIA_ROOT/{Audio,Videos,Images,Documents}`, the same four on the external volume,
   and `COOLIFY_STORAGE/{ssh,applications,databases,services,backups,postgres,redis}`. It warns
   loudly if the external volume is not actually mounted.

It is idempotent — running it twice changes nothing the second time.

**Check:** no secret is left empty, and no path still says `CHANGEME`.

```bash
grep -rn 'CHANGEME' --include='.env' .                     # must print nothing
grep -HE '^[A-Z_]+=$' .env */.env || echo "All keys filled ✓"
```

**Check:** your secrets are ignored by git.

```bash
git status --short                       # no .env should appear
git check-ignore -v .env coolify/.env papra-doc/.env immich-photos/.env
```

### Doing it by hand instead

`configure.sh` is a convenience, not a requirement. Each service reads the `.env` sitting next to
its `docker-compose.yml`, so this is equivalent:

```bash
cp jellyfin/.env.example jellyfin/.env
$EDITOR jellyfin/.env      # set TZ, PUID, PGID, MEDIA_ROOT, EXTERNAL_STORAGE
```

Compose fails with a clear message if a required variable is missing — it will never silently
mount the wrong thing:

```text
required variable MEDIA_ROOT is missing a value: set MEDIA_ROOT in .env — run ./configure.sh
```

---

## Step 4 — Platform-specific tuning (optional)

Everything runs with defaults. These are the knobs worth turning on each OS.

### 🐧 Linux tuning

| What                              | Where                                  | Why                                                                                      |
| --------------------------------- | -------------------------------------- | ---------------------------------------------------------------------------------------- |
| **Home Assistant host net**       | `home-assistant/docker-compose.yml`    | Uncomment `network_mode: host` and comment out `ports:` — mDNS/SSDP discovery then works |
| **Zigbee/Z-Wave dongle**          | `home-assistant/docker-compose.yml`    | Uncomment `devices:` and point it at `/dev/serial/by-id/...`                             |
| **Jellyfin transcoding**          | `jellyfin/docker-compose.yml` + `.env` | Uncomment the `devices: /dev/dri` block, set `RENDER_GID` — real hardware transcoding    |
| **Immich ML on GPU**              | `immich-photos/docker-compose.yml`     | Use the `-cuda` image tag and uncomment `deploy:` — imports go from hours to minutes     |
| **Coolify manages the host**      | `coolify/docker-compose.yml`           | Uncomment the `/var/run/docker.sock` mount — this is the whole point of Coolify          |
| **Coolify storage on local disk** | `coolify/.env` → `COOLIFY_STORAGE`     | Postgres on NFS/SMB is slow and corruption-prone. Point it at e.g. `/data/coolify`       |

Driver prerequisites for the GPU rows are in
[DOCKER-INSTALL.md § Optional Linux extras](./DOCKER-INSTALL.md#optional-linux-extras).

### 🍎 macOS tuning

| What               | Where                                     | Why                                                                       |
| ------------------ | ----------------------------------------- | ------------------------------------------------------------------------- |
| **VM memory**      | Docker Desktop → Resources → Memory       | The 8 GB default does not fit these stacks. Give it ~16 GB on a 32 GB Mac |
| **File sharing**   | Docker Desktop → Resources → File sharing | Must include your home dir and `/Volumes`, or bind mounts fail            |
| **Start at login** | Docker Desktop → General                  | `restart: unless-stopped` is useless if the daemon never starts           |

The Linux rows above have **no macOS equivalent** — Docker Desktop's VM cannot pass through a GPU
or a USB dongle, and its NAT'd network blocks L2 discovery. See
[REQUIREMENTS.md § Platform differences](./REQUIREMENTS.md#platform-differences).

---

## Step 5 — Bring the services up

Start them one at a time on a first run so a failure is obvious. Portainer goes first — it gives
you a web UI to watch everything else come up.

Each block is: start it, then confirm it. `open` below is macOS; on Linux use `xdg-open`, or just
paste the URL into a browser.

### 5.1 Portainer — port 9000

```bash
docker compose -f portainer/docker-compose.yaml up -d
open http://localhost:9000          # 🐧 xdg-open
```

Create the admin account **immediately** — Portainer disables new-admin setup a few minutes after
it starts. If you hit that, restart the container and retry.

### 5.2 Jellyfin — port 8096

```bash
docker compose -f jellyfin/docker-compose.yml up -d
open http://localhost:8096
```

In the wizard, add libraries pointing at `/data/videos` and `/data/videos-external`.

### 5.3 Audiobookshelf — port 13378

```bash
docker compose -f audiobookshelf/docker-compose.yml up -d
open http://localhost:13378
```

Libraries live at `/audiobooks`, `/books`, `/audiobooks-external`, `/books-external`.

### 5.4 Home Assistant — port 8123

```bash
docker compose -f home-assistant/docker-compose.yml up -d
open http://localhost:8123
```

Give it 1–2 minutes on first boot — it generates its config before serving. It runs `privileged`
with `NET_ADMIN`/`NET_RAW`, so treat `home-assistant/config/` as security-sensitive.

🐧 On Linux, switch it to `network_mode: host` (Step 4) if you want device discovery.
🍎 On macOS, discovery will not work regardless — the Docker VM is NAT'd off your LAN.

### 5.5 Obsidian — port 3000

```bash
docker compose -f obsidian-brain/docker-compose.yml up -d
open http://localhost:3000
```

A full Obsidian GUI in the browser, not an API. Vaults go under `./obsidian/config`. It runs as
your `PUID`/`PGID`, so the vault stays editable from the host on both OSes.

### 5.6 Papra — port 1221

```bash
docker compose -f papra-doc/docker-compose.yml up -d
open http://localhost:1221
```

Its data folder is `EXTERNAL_STORAGE/Documents`; `MEDIA_ROOT/Documents` is mounted separately at
`/data/documents` for imports.

### 5.7 Immich — port 2283 (4 containers)

```bash
docker compose -f immich-photos/docker-compose.yml up -d
docker compose -f immich-photos/docker-compose.yml ps      # all 4 should be Up
open http://localhost:2283
```

First start is slow: Postgres initialises and the ML container downloads models into `./ml-cache`.
Watch it if you are impatient:

```bash
docker compose -f immich-photos/docker-compose.yml logs -f immich-server
```

Photos are at `/mnt/external-data` (read-write, external volume) and `/mnt/external-library`
(**read-only**, your `MEDIA_ROOT/Images`).

### 5.8 Coolify — port 8000 (4 containers)

**Confirm the storage is mounted before this one** (Step 2). Coolify keeps all its state there.

```bash
ls "$(grep '^COOLIFY_STORAGE=' coolify/.env | cut -d= -f2-)"    # must exist, on real storage
docker compose -f coolify/docker-compose.yml up -d
docker compose -f coolify/docker-compose.yml ps
open http://localhost:8000
```

The `coolify` container has `depends_on: condition: service_healthy` for Postgres, Redis and
soketi, so it stays in `Created` until all three pass their healthchecks. On slow storage that
takes a couple of minutes — normal, not a failure. Check `ps` before debugging.

🐧 On Linux this is a real PaaS: give it the Docker socket (Step 4) and it can deploy to this host.
🍎 On macOS it installs and the UI works, but it cannot manage the Mac itself — it expects to SSH
into a Linux host, and the daemon lives inside a VM. Treat it as a dashboard, not a deploy target.

---

## Step 6 — Verify everything

```bash
docker ps                 # 14 containers across the 8 stacks
./test-services.sh
```

`test-services.sh` prints container health, curls each service, and reports whether each Tailscale
peer is `[DIRECT]` or `[RELAY]`. It probes `SERVICE_HOST` from the root `.env` (default
`127.0.0.1`); override it to check remote reachability:

```bash
SERVICE_HOST=100.105.40.95 ./test-services.sh
```

**A healthy run** shows `[OK]` for all 8 services. Codes `200`, `301`, `302`, `400`, `401` and
`403` all count as OK — a login redirect still proves the service is listening. If Tailscale is
not installed, that section is skipped rather than failing.

---

## Step 7 — Remote access over Tailscale

Optional, but it is how the lab is reached from outside the house.

```bash
# 🍎 macOS
brew install --cask tailscale        # or the Mac App Store build
# 🐧 Linux
curl -fsSL https://tailscale.com/install.sh | sh

sudo tailscale up
tailscale status
```

🐧 On Linux, also enable it at boot: `sudo systemctl enable --now tailscaled`.

Every service is then reachable from any device on your tailnet:

```text
http://<your-machine>.<your-tailnet>.ts.net:<port>
```

| Port | Service        |     | Port  | Service        |
| ---- | -------------- | --- | ----- | -------------- |
| 1221 | Papra          |     | 8000  | Coolify        |
| 2283 | Immich         |     | 8096  | Jellyfin       |
| 3000 | Obsidian       |     | 8123  | Home Assistant |
| 6001 | Coolify soketi |     | 9000  | Portainer      |
|      |                |     | 13378 | Audiobookshelf |

🐧 **Linux firewall.** Unlike macOS, most Linux distros ship a firewall that is on. Open the ports
for the tailnet only — never `0.0.0.0`:

```bash
# ufw (Debian/Ubuntu)
sudo ufw allow in on tailscale0
sudo ufw reload

# firewalld (Fedora/RHEL)
sudo firewall-cmd --permanent --zone=trusted --add-interface=tailscale0
sudo firewall-cmd --reload
```

If `test-services.sh` reports `[RELAY]`, traffic is going through a DERP relay instead of a direct
connection — it works but is slow and drops long-lived sessions. The fix is a UDP 41641 port
forward on your router; see
[PLAN.md § Troubleshooting](./PLAN.md#troubleshooting-services-not-reachable-from-tailscale-peers).

---

## Day-two operations

**Update everything** (pull latest images, recreate containers, then health-check):

```bash
./restart-all.sh
./restart-all.sh --no-pull      # recreate without pulling
./restart-all.sh --no-test      # skip the health check
```

It runs in this order — `audiobookshelf → coolify → papra-doc → home-assistant → jellyfin →
immich-photos → portainer → obsidian-brain` — skips any directory with no compose file, skips any
service missing its `.env`, and calls `test-services.sh` at the end. It exits non-zero if any
stack failed.

**One service:**

```bash
docker compose -f <service-dir>/docker-compose.yml pull
docker compose -f <service-dir>/docker-compose.yml up -d --remove-orphans
```

**Logs:** `docker compose -f <service-dir>/docker-compose.yml logs -f`

**Stop one:** `docker compose -f <service-dir>/docker-compose.yml down`
(add `-v` only if you truly want to delete its named volumes — for Portainer that erases your
Portainer config).

**Move your storage:** edit `MEDIA_ROOT` / `EXTERNAL_STORAGE` in the root `.env`, re-run
`./configure.sh`, then `./restart-all.sh`.

🐧 **Reboot survival on Linux:** `restart: unless-stopped` only helps if the daemon starts.
`sudo systemctl enable docker` once, and confirm with `systemctl is-enabled docker`.

---

## Migrating from the placeholder layout

If you have an older checkout where you ran `sed` over the compose files:

```bash
# 1. Discard the machine-local substitutions — they are no longer needed.
git update-index --no-skip-worktree $(git ls-files '*.yml' '*.yaml') 2>/dev/null || true
git checkout -- '*.yml' '*.yaml'

# 2. Pull the new layout, then configure.
git pull
cp .env.example .env
$EDITOR .env          # MEDIA_ROOT + EXTERNAL_STORAGE — note EXTERNAL_STORAGE is now a FULL PATH,
                      # e.g. /Volumes/NAS, not just "NAS"
./configure.sh        # keeps every secret you already had

# 3. Restart.
./restart-all.sh
```

`configure.sh` also drops the old `UID`/`GID` keys from `papra-doc/.env`, replaced by
`PUID`/`PGID`. Nothing else about your data moves — the bind-mount targets resolve to the same
paths they did before.

---

## Troubleshooting

| Symptom                                           | OS   | Cause                                                                         | Fix                                                                                          |
| ------------------------------------------------- | ---- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `required variable MEDIA_ROOT is missing a value` | both | No `.env` next to that compose file                                           | `./configure.sh`                                                                             |
| Service starts but its library is empty           | both | `EXTERNAL_STORAGE` points at an unmounted path                                | Re-do Step 2, delete the empty stub directory, restart the stack                             |
| `path ... is not shared from the host`            | 🍎   | Docker Desktop file sharing                                                   | Settings → Resources → File sharing: add your home dir and `/Volumes`                        |
| `permission denied` writing to a mounted share    | 🐧   | CIFS/NFS mounted as root                                                      | Add `uid=$(id -u),gid=$(id -g)` to the fstab options, or fix ownership on the NFS export     |
| Files owned by a uid that does not exist          | both | `PUID`/`PGID` do not match your user                                          | `id -u; id -g`, fix the root `.env`, re-run `./configure.sh`, recreate the container         |
| Coolify UI never leaves `Created`                 | both | Waiting on postgres/redis/soketi healthchecks                                 | `docker compose -f coolify/docker-compose.yml ps`; wait 2 min; then `docker logs coolify-db` |
| Coolify came up empty / lost its data             | both | Started with the storage unmounted, so Postgres made a fresh DB on a stub dir | `down`, verify Step 2, remount, bring it up again                                            |
| Coolify cannot deploy anything                    | 🍎   | Expected — it needs a Linux host it can SSH into                              | Not fixable on macOS; use it as a dashboard only                                             |
| Home Assistant finds no devices                   | 🍎   | The Docker VM is NAT'd; no L2 broadcast                                       | Not fixable on macOS                                                                         |
| Home Assistant finds no devices                   | 🐧   | Bridge networking blocks mDNS/SSDP                                            | Switch to `network_mode: host` (Step 4)                                                      |
| Jellyfin pegs the CPU while streaming             | 🍎   | No GPU passthrough, so every transcode is CPU-only                            | Force direct-play in the client, or move to a Linux host                                     |
| Jellyfin pegs the CPU while streaming             | 🐧   | Hardware transcoding not enabled                                              | Uncomment the `/dev/dri` block (Step 4) and enable VAAPI/QSV in Jellyfin's dashboard         |
| Immich errors after an update                     | both | Pending DB migrations                                                         | `docker compose -f immich-photos/docker-compose.yml logs -f immich-db`; pin `IMMICH_VERSION` |
| Port already in use                               | 🍎   | Another process holds it                                                      | `lsof -i :<port>`                                                                            |
| Port already in use                               | 🐧   | Another process holds it                                                      | `sudo ss -lptn "sport = :<port>"`                                                            |
| Containers gone after a reboot                    | 🐧   | Docker not enabled as a service                                               | `sudo systemctl enable --now docker`                                                         |
| Containers gone after a reboot                    | 🍎   | Docker Desktop not set to start at login                                      | Settings → General → Start Docker Desktop when you log in                                    |
| Reachable locally, not from other devices         | both | Tailscale DERP relay, or a Linux firewall                                     | See Step 7                                                                                   |
