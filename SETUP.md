# Setup Guide — Mounting the Whole Home Lab

A start-to-finish walkthrough for bringing every service in this repo online on a fresh Mac mini.
Follow the steps in order; each one ends with a check you can run before moving on.

For _what_ each service is and where its data lives, see **[PLAN.md](./PLAN.md)**.

**Time:** ~30–45 minutes, most of it image pulls.

---

## Before you start

You will substitute two values everywhere in this guide. Write them down now:

| Placeholder          | How to find it                               | Yours |
| -------------------- | -------------------------------------------- | ----- |
| `<ROOT_USERNAME>`    | `whoami`                                     |       |
| `<EXTERNAL_STORAGE>` | `ls /Volumes` — the NAS / external disk name |       |

---

## Step 1 — Prerequisites

```bash
# Docker Desktop must be installed and RUNNING (whale icon in the menu bar).
docker --version          # any recent version
docker compose version    # must exist — this repo uses the compose *plugin*, not docker-compose
docker ps                 # must succeed; if it errors, Docker Desktop isn't running

# Tailscale, for remote access
tailscale status
```

Then make the scripts executable:

```bash
cd ~/Documents/projects/homelab-servers   # or wherever you cloned this
chmod +x restart-all.sh test-services.sh
```

**Check:** `docker ps` prints a header row without error.

---

## Step 2 — Substitute the placeholders

> **This is the step people skip, and skipping it breaks everything.**
> The compose files contain the literal text `<ROOT_USERNAME>` and `<EXTERNAL_STORAGE>`.
> Docker Compose does **not** expand `<...>` — it is not `${VAR}` syntax. If you start a stack
> without substituting, Docker happily creates a directory literally named
> `/Users/<ROOT_USERNAME>` and mounts that empty directory. Your containers come up looking
> completely empty and you will spend an hour wondering why.

Set your two values and rewrite the compose files in place:

```bash
ROOT_USERNAME="$(whoami)"
EXTERNAL_STORAGE="NAS"          # ← change to your actual volume name from `ls /Volumes`

# macOS sed needs the empty-string argument after -i
grep -rl '<ROOT_USERNAME>\|<EXTERNAL_STORAGE>' --include='*.yml' --include='*.yaml' . \
  | xargs sed -i '' \
      -e "s|<ROOT_USERNAME>|${ROOT_USERNAME}|g" \
      -e "s|<EXTERNAL_STORAGE>|${EXTERNAL_STORAGE}|g"
```

**Check:** this must print nothing.

```bash
grep -rn '<ROOT_USERNAME>\|<EXTERNAL_STORAGE>' --include='*.yml' --include='*.yaml' .
```

> **Don't commit the result.** `git status` will now show every compose file as modified. Those
> edits are machine-local. Either leave them uncommitted, or hide them from git with:
>
> ```bash
> git update-index --skip-worktree $(git ls-files '*.yml' '*.yaml')
> ```
>
> (undo later with `--no-skip-worktree`).

---

## Step 3 — Mount the external storage

`/Volumes/<EXTERNAL_STORAGE>` is a bind-mount source for audiobookshelf, jellyfin, immich, papra,
and **all** of Coolify. It must be mounted _before_ any stack starts.

```bash
ls "/Volumes/${EXTERNAL_STORAGE}"
```

If that fails, mount it in Finder (⌘K for a network share) and re-check. In Finder, set
**System Settings → General → Login Items** to remount it at boot so a reboot doesn't silently
detach your storage.

> **Why this matters:** if the volume is missing, Docker creates an empty directory at that path
> instead of failing. Coolify's postgres would then initialize a brand-new empty database, and you
> lose your Coolify state. Never start Coolify with the NAS unmounted.

**Check:**

```bash
ls "/Volumes/${EXTERNAL_STORAGE}"                    # your NAS contents
mount | grep "${EXTERNAL_STORAGE}"                   # confirms it's a real mount, not a stub dir
```

---

## Step 4 — Create the host media directories

These are bind-mount sources on the internal disk. Docker would create them as `root`-owned if
missing; create them yourself so they belong to you.

```bash
mkdir -p ~/Audio ~/Videos ~/Images ~/Documents

# NAS-side counterparts
mkdir -p "/Volumes/${EXTERNAL_STORAGE}"/{Audio,Videos,Images,Documents}
mkdir -p "/Volumes/${EXTERNAL_STORAGE}/Storage/coolify"/{ssh,applications,databases,services,backups,postgres,redis}
```

Then grant Docker Desktop access to them: **Docker Desktop → Settings → Resources → File sharing**
must include your home directory and `/Volumes`. Without this, bind mounts fail with a
"path is not shared" error.

**Check:** `ls -ld ~/Audio ~/Videos ~/Images ~/Documents` shows your user as owner.

---

## Step 5 — Fill in the secrets

Three services need a `.env`. Each ships an `.env.example` template with the right keys and no values.

```bash
cp papra-doc/.env.example      papra-doc/.env
cp immich-photos/.env.example  immich-photos/.env
cp coolify/.env.example        coolify/.env
```

Generate values with `openssl` and paste them in:

```bash
openssl rand -hex 32                      # AUTH_SECRET (papra)
openssl rand -hex 24                      # any DB_PASSWORD / REDIS_PASSWORD / PUSHER_APP_KEY|SECRET
openssl rand -hex 16                      # APP_ID / PUSHER_APP_ID (coolify)
echo "base64:$(openssl rand -base64 32)"  # APP_KEY (coolify) — keep the base64: prefix
id -u; id -g                              # UID / GID for papra (usually 501 and 20)
```

Fill in every blank key:

| File                 | Keys that must not stay empty                                                    |
| -------------------- | -------------------------------------------------------------------------------- |
| `papra-doc/.env`     | `AUTH_SECRET`; confirm `UID`/`GID` match `id -u` / `id -g`                       |
| `immich-photos/.env` | `DB_PASSWORD`                                                                    |
| `coolify/.env`       | `APP_ID`, `APP_KEY`, `DB_PASSWORD`, `REDIS_PASSWORD`, `PUSHER_APP_ID/KEY/SECRET` |

**Check:** no key is left with an empty value.

```bash
grep -H '=$' papra-doc/.env immich-photos/.env coolify/.env || echo "All keys filled ✓"
```

**Check:** your secrets are ignored by git.

```bash
git status --short          # no .env files should appear
git check-ignore -v coolify/.env papra-doc/.env immich-photos/.env
```

---

## Step 6 — Bring the services up

Start them one at a time on a first run so a failure is obvious. Portainer goes first — it gives
you a web UI to watch everything else come up.

Each block is: start it, then confirm it.

### 6.1 Portainer — port 9000

```bash
docker compose -f portainer/docker-compose.yaml up -d
open http://localhost:9000
```

Create the admin account **immediately** — Portainer locks out new-admin setup after a few minutes
of being up. If you hit that, restart the container and retry.

### 6.2 Jellyfin — port 8096

```bash
docker compose -f jellyfin/docker-compose.yml up -d
open http://localhost:8096
```

In the setup wizard, add libraries pointing at `/data/videos` and `/data/videos-external`.

### 6.3 Audiobookshelf — port 13378

```bash
docker compose -f audiobookshelf/docker-compose.yml up -d
open http://localhost:13378
```

Libraries live at `/audiobooks`, `/books`, `/audiobooks-external`, `/books-external`.

### 6.4 Home Assistant — port 8123

```bash
docker compose -f home-assistant/docker-compose.yml up -d
open http://localhost:8123
```

Give it 1–2 minutes on first boot — it generates its config before serving. This one runs
`privileged` with `NET_ADMIN`/`NET_RAW`, so treat `home-assistant/config/` as sensitive.

### 6.5 Obsidian — port 3000

```bash
docker compose -f obsidian-brain/docker-compose.yml up -d
open http://localhost:3000
```

You get a full Obsidian GUI in the browser, not an API. Vaults go under `./obsidian/config`.

> **Known wart:** this stack uses `PUID=1000` / `PGID=1000`, while everything else uses the macOS
> pair `501`/`20`. Files it writes will be owned by a UID that doesn't exist on your Mac. If you
> want to edit the vault from Finder, change those two values in
> `obsidian-brain/docker-compose.yml` to `501` and `20` and recreate the container.

### 6.6 Papra — port 1221

```bash
docker compose -f papra-doc/docker-compose.yml up -d
open http://localhost:1221
```

> **Known wart:** the compose file mounts _two_ host paths onto `/app/app-data` (`./` and
> `/Volumes/<EXTERNAL_STORAGE>/Documents`). The second wins; the first is dead weight. Harmless
> today, but delete one of the two next time you edit that file.

### 6.7 Immich — port 2283 (4 containers)

```bash
docker compose -f immich-photos/docker-compose.yml up -d
docker compose -f immich-photos/docker-compose.yml ps      # all 4 should be Up
open http://localhost:2283
```

First start is slow: postgres initializes and the ML container downloads models into `./ml-cache`.
Watch it if you're impatient:

```bash
docker compose -f immich-photos/docker-compose.yml logs -f immich-server
```

Photos are at `/mnt/external-data` (read-write, NAS) and `/mnt/external-library`
(**read-only**, your `~/Images`).

### 6.8 Coolify — port 8000 (4 containers)

**Confirm the NAS is mounted before this one** (Step 3). Coolify keeps all of its state there.

```bash
ls "/Volumes/${EXTERNAL_STORAGE}/Storage/coolify"     # must exist and be on the real NAS
docker compose -f coolify/docker-compose.yml up -d
docker compose -f coolify/docker-compose.yml ps
open http://localhost:8000
```

The `coolify` UI container has `depends_on: condition: service_healthy` for postgres, redis, and
soketi, so it stays in `Created` until all three pass healthchecks. On a slow NAS this takes a
couple of minutes — that is normal, not a failure. Check with `ps` before debugging.

---

## Step 7 — Verify everything

```bash
docker ps                # 13 containers across the 8 stacks
./test-services.sh
```

`test-services.sh` prints container health, curls each service over the Tailscale IP, and then
reports whether each Tailscale peer is `[DIRECT]` or `[RELAY]`.

**A healthy run** shows `[OK]` for all 8 services. Codes `200`, `301`, `302`, `400`, `401`, and
`403` all count as OK — a login redirect still proves the service is listening.

---

## Step 8 — Remote access over Tailscale

Once Tailscale is up on the Mac mini, every service is reachable from any device on your tailnet:

```text
http://<YOUR TAILSCALE ADDRESS>.ts.net:<port>
http://100.105.40.95:<port>
```

| Port | Service        |     | Port  | Service        |
| ---- | -------------- | --- | ----- | -------------- |
| 1221 | Papra          |     | 8000  | Coolify        |
| 2283 | Immich         |     | 8096  | Jellyfin       |
| 3000 | Obsidian       |     | 8123  | Home Assistant |
| 6001 | Coolify soketi |     | 9000  | Portainer      |
|      |                |     | 13378 | Audiobookshelf |

If `test-services.sh` reports `[RELAY]` for your peers, traffic is going through a DERP relay
instead of a direct connection — it works but is slow and can drop long-lived sessions. The fix is
a UDP 41641 port-forward on your router; see
[PLAN.md § Troubleshooting](./PLAN.md#troubleshooting-services-not-reachable-from-tailscale-peers).

---

## Day-two operations

**Update everything** (pull latest images, recreate containers, then health-check):

```bash
./restart-all.sh
```

It runs in this order — `audiobookshelf → coolify → papra-doc → home-assistant → jellyfin →
immich-photos → portainer → obsidian-brain` — skips any directory with no compose file, and calls
`test-services.sh` at the end.

**One service:**

```bash
docker compose -f <service-dir>/docker-compose.yml pull
docker compose -f <service-dir>/docker-compose.yml up -d --remove-orphans
```

**Logs:** `docker compose -f <service-dir>/docker-compose.yml logs -f`

**Stop one:** `docker compose -f <service-dir>/docker-compose.yml down`
(add `-v` only if you truly want to delete its named volumes — for Portainer that erases your
Portainer config).

---

## Troubleshooting

| Symptom                                       | Cause                                                                                  | Fix                                                                                                                    |
| --------------------------------------------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Service starts but its library is empty       | Placeholders never substituted — Docker mounted a literal `<ROOT_USERNAME>` directory  | Re-run Step 2, then `ls /Users/` and `ls /Volumes/` and delete the bogus `<...>` directories                           |
| `Error: path ... is not shared from the host` | Docker Desktop file sharing                                                            | Add your home dir and `/Volumes` under Settings → Resources → File sharing                                             |
| Coolify UI never leaves `Created`             | Waiting on postgres/redis/soketi healthchecks                                          | `docker compose -f coolify/docker-compose.yml ps`; give it 2 min; then check `docker logs coolify-db`                  |
| Coolify came up empty / lost its data         | Started with the NAS unmounted, so postgres initialized a fresh DB on a stub directory | `down`, verify Step 3, remount, bring it up again                                                                      |
| `variable is not set` warnings on `up`        | `.env` missing or a key left blank                                                     | Re-do Step 5 for that service                                                                                          |
| Papra exits immediately                       | `UID`/`GID` missing from `papra-doc/.env` (`user:` gets an empty value)                | Set them to `id -u` / `id -g`                                                                                          |
| Immich errors after an update                 | Pending DB migrations                                                                  | `docker compose -f immich-photos/docker-compose.yml logs -f immich-db`; pin `IMMICH_VERSION` to control upgrade timing |
| Port already in use                           | Another process holds it                                                               | `lsof -i :<port>` to find it                                                                                           |
| Reachable locally, not from other devices     | Tailscale DERP relay                                                                   | See Step 8 / PLAN.md troubleshooting                                                                                   |
