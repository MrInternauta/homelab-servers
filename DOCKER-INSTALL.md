# Installing Docker — macOS and Linux

This lab needs **Docker Engine plus the `docker compose` v2 plugin**. It does _not_ use the
old standalone `docker-compose` (v1) binary; every command in this repo is `docker compose`
(space, not hyphen).

Jump to: [macOS](#macos) · [Linux](#linux) · [Verify](#verify-the-install) ·
[Troubleshooting](#troubleshooting)

> Companion docs: **[SETUP.md](./SETUP.md)** (bring the lab up once Docker works),
> **[REQUIREMENTS.md](./REQUIREMENTS.md)** (how much machine you need).

---

## macOS

Two options. **Docker Desktop** is the default and what the rest of this repo assumes.
**Colima** is a lighter, fully open-source alternative if you would rather not run Desktop.

### Option A — Docker Desktop (recommended)

```bash
# With Homebrew:
brew install --cask docker

# Or download the .dmg matching your chip from:
#   https://www.docker.com/products/docker-desktop/
#   Apple silicon (M1–M4) → "Mac with Apple chip"
#   Intel                 → "Mac with Intel chip"
```

Then **launch Docker.app once** — the CLI does nothing until the whale icon is in the menu bar.
Confirm which chip you are on with `uname -m` (`arm64` = Apple silicon, `x86_64` = Intel).

Docker Desktop ships the compose plugin, buildx, and the VM. Configure it before starting the lab:

| Docker Desktop → Settings                          | Set it to                                                        |
| -------------------------------------------------- | ---------------------------------------------------------------- |
| **General → Start Docker Desktop when you log in** | On — otherwise nothing comes back after a reboot                 |
| **Resources → Memory**                             | ~16 GB on a 32 GB Mac (see [REQUIREMENTS.md](./REQUIREMENTS.md)) |
| **Resources → CPUs**                               | 6–8                                                              |
| **Resources → File sharing**                       | Must list your home directory **and** `/Volumes`                 |

That last one is the one people miss. Without it, bind mounts fail with
`Error response from daemon: ... path ... is not shared from the host`.

> **Licensing:** Docker Desktop requires a paid subscription for larger companies. Personal use,
> education, and small businesses are free. Colima has no such condition.

### Option B — Colima (no Docker Desktop)

```bash
brew install colima docker docker-compose docker-credential-helper

# Make the compose plugin discoverable (Homebrew prints this too):
mkdir -p ~/.docker/cli-plugins
ln -sfn "$(brew --prefix)/opt/docker-compose/bin/docker-compose" ~/.docker/cli-plugins/docker-compose

# Start a VM sized for this lab, with your home dir writable inside it:
colima start --cpu 6 --memory 16 --disk 200 --mount-type virtiofs --mount "$HOME:w"

# Start it automatically at login:
brew services start colima
```

Colima mounts only what you tell it to. If your external storage is under `/Volumes`, add it:

```bash
colima start --mount "/Volumes/YourVolume:w"
```

Colima's VM has the same limits as Docker Desktop's — no GPU passthrough, NAT'd networking.

---

## Linux

Install **Docker Engine from Docker's own repository**, not your distro's `docker.io` package —
distro packages are often old and sometimes ship compose v1 only.

### Debian / Ubuntu (and derivatives)

```bash
# 1. Remove any distro-packaged Docker that would conflict
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt-get remove -y "$pkg" 2>/dev/null || true
done

# 2. Add Docker's GPG key and repository
#    Ubuntu → .../linux/ubuntu   |   Debian → .../linux/debian
DISTRO=ubuntu   # change to: debian
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL "https://download.docker.com/linux/${DISTRO}/gpg" -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/${DISTRO} \
$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 3. Install the engine, the CLI, buildx and the compose plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
                        docker-buildx-plugin docker-compose-plugin
```

`${UBUNTU_CODENAME:-$VERSION_CODENAME}` matters on derivatives: on Linux Mint or Pop!\_OS,
`VERSION_CODENAME` is the derivative's own name, which Docker's repo does not know.

### Fedora / RHEL / Rocky / Alma

```bash
sudo dnf -y install dnf-plugins-core

# Fedora:
sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
# RHEL / Rocky / Alma:
# sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo

# dnf5 (Fedora 41+) uses a different flag:
# sudo dnf config-manager addrepo --from-repofile=https://download.docker.com/linux/fedora/docker-ce.repo

sudo dnf install -y docker-ce docker-ce-cli containerd.io \
                    docker-buildx-plugin docker-compose-plugin
```

### Arch / Manjaro

```bash
sudo pacman -Syu --needed docker docker-compose docker-buildx
```

Arch's `docker-compose` package _is_ the v2 plugin, so `docker compose` works.

### openSUSE

```bash
sudo zypper install -y docker docker-compose docker-compose-switch
```

### Any distro — Docker's convenience script

Fine for a personal box, discouraged for anything you care about (it pipes a remote script into
root's shell and pins nothing):

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
less get-docker.sh          # read it before running it
sudo sh get-docker.sh
```

### Post-install (Linux, required)

```bash
# 1. Start Docker now and on every boot — this is what makes `restart: unless-stopped` work
sudo systemctl enable --now docker containerd

# 2. Run docker without sudo
sudo groupadd -f docker
sudo usermod -aG docker "$USER"
newgrp docker           # or log out and back in
```

> **Security:** membership in the `docker` group is equivalent to root on that machine — the
> daemon will happily bind-mount `/` into a container. On a shared box, prefer
> [rootless mode](https://docs.docker.com/engine/security/rootless/) — though note that Portainer's
> `/var/run/docker.sock` mount and Home Assistant's `privileged: true` both expect the normal
> rootful daemon, so rootless will need adjusting.

### Optional Linux extras

**Hardware transcoding for Jellyfin (Intel/AMD).** Install the VAAPI drivers, then uncomment the
`devices:` block in `jellyfin/docker-compose.yml`:

```bash
# Debian/Ubuntu
sudo apt-get install -y intel-media-va-driver-non-free vainfo   # Intel
sudo apt-get install -y mesa-va-drivers vainfo                  # AMD
ls -l /dev/dri                       # renderD128 should exist
getent group render | cut -d: -f3    # put this in jellyfin/.env as RENDER_GID
```

**NVIDIA GPU (Jellyfin NVENC, Immich ML).** Install the NVIDIA Container Toolkit, then uncomment
the `deploy:` blocks in `jellyfin/docker-compose.yml` and `immich-photos/docker-compose.yml`:

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

**Docker Desktop for Linux** exists, but it runs the engine inside a VM — the exact thing you
avoid by using Linux. Use Docker Engine directly.

---

## Verify the install

Same on both OSes:

```bash
docker --version           # Docker version 24+ (27+ preferred)
docker compose version     # must print v2.x — if "command not found", the plugin is missing
docker info                # must succeed; talks to the daemon
docker run --rm hello-world
```

All four clean? Go to **[SETUP.md](./SETUP.md)**.

---

## Troubleshooting

| Symptom                                                                 | OS    | Fix                                                                                                                                     |
| ----------------------------------------------------------------------- | ----- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `Cannot connect to the Docker daemon at unix:///var/run/docker.sock`    | macOS | Docker Desktop / Colima is not running. Launch it.                                                                                      |
| same                                                                    | Linux | `sudo systemctl start docker`, then check you are in the `docker` group (`id -nG`)                                                      |
| `permission denied while trying to connect to the Docker daemon socket` | Linux | You are not in the `docker` group yet, or have not re-logged in. `newgrp docker`                                                        |
| `docker: 'compose' is not a docker command`                             | both  | The v2 plugin is missing. Install `docker-compose-plugin` (Linux) or link it (Colima)                                                   |
| `path /Users/... is not shared from the host`                           | macOS | Docker Desktop → Settings → Resources → File sharing: add your home dir and `/Volumes`                                                  |
| `path /mnt/... is not shared`                                           | macOS | Colima only mounts what `--mount` names. Restart Colima with the path added                                                             |
| Containers do not come back after a reboot                              | Linux | `sudo systemctl enable docker` — `restart: unless-stopped` only works if the daemon starts                                              |
| Containers do not come back after a reboot                              | macOS | Docker Desktop → Settings → General → "Start Docker Desktop when you log in"                                                            |
| `no matching manifest for linux/arm64`                                  | macOS | An amd64-only image on Apple silicon. It will run under emulation; check with `docker image inspect <img> --format '{{.Architecture}}'` |
| Port already in use                                                     | both  | macOS: `lsof -i :<port>` · Linux: `sudo ss -lptn "sport = :<port>"`                                                                     |
