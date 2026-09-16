# Hardware Requirements — Sizing the Host

Approximate resource requirements for running all 8 stacks (**14 containers**) in this repo on a
single machine, on **macOS (Docker Desktop / Colima)** or **Linux (Docker Engine)**.

> Companion docs: **[SETUP.md](./SETUP.md)** (bring-up),
> **[DOCKER-INSTALL.md](./DOCKER-INSTALL.md)** (installing Docker),
> **[PLAN.md](./PLAN.md)** (services, ports, storage), `README.md`.

RAM figures are steady-state RSS **of the containers themselves**. On macOS they sit inside the
Docker VM and exclude macOS and the VM's own overhead; on Linux they are simply processes on the
host. Whole-machine totals are in [Machine totals](#machine-totals).

## Per-Service Resource Estimates

| Stack              | Containers                       | Idle RAM    | Busy RAM           | CPU (busy)                        |
| ------------------ | -------------------------------- | ----------- | ------------------ | --------------------------------- |
| **immich-photos**  | 4 (server, ml, db, valkey)       | ~2.5 GB     | **4–6 GB**         | 4+ cores during import            |
| **obsidian-brain** | 1 (Chromium + KasmVNC)           | ~700 MB     | 1.5–2 GB           | 1–2 cores when open               |
| **coolify**        | 4 (php-fpm, pg15, redis, soketi) | ~1 GB       | 1.5–2 GB           | 0.5 core, spikes on builds        |
| **home-assistant** | 1                                | ~500 MB     | 1–1.5 GB           | 0.3–1 core                        |
| **jellyfin**       | 1                                | ~300 MB     | +250 MB/stream     | **2–4 cores per 1080p transcode** |
| **audiobookshelf** | 1                                | ~200 MB     | 600 MB–1 GB (scan) | 0.5 core during library scan      |
| **papra-doc**      | 1                                | ~200 MB     | ~700 MB (OCR)      | 1 core during OCR                 |
| **portainer**      | 1                                | ~60 MB      | ~100 MB            | negligible                        |
| **Total**          | **14**                           | **~5.5 GB** | **10–14 GB**       | —                                 |

The two workloads that actually saturate the machine are Immich's ML pass (CLIP embeddings + face
detection across the whole library) and Jellyfin transcoding. Everything else is close to free.

**Both of those are dramatically cheaper on Linux with a GPU** — see
[Platform differences](#platform-differences).

## Machine Totals

| Resource  | 🍎 macOS minimum | 🍎 macOS recommended | 🐧 Linux minimum | 🐧 Linux recommended | Notes                                  |
| --------- | ---------------- | -------------------- | ---------------- | -------------------- | -------------------------------------- |
| RAM       | 16 GB            | **32 GB**            | 12 GB            | **16–32 GB**         | Linux has no VM to pay for             |
| CPU       | 6 cores          | **8 cores**          | 4 cores          | **6–8 cores**        | Fewer if a GPU handles transcode/ML    |
| Boot disk | 256 GB           | **512 GB**           | 128 GB           | **256–512 GB**       | Images alone are ~18–22 GB before data |

**RAM.** 🍎 On macOS, Docker Desktop's VM memory is a **fixed allocation** you set in its settings —
the default (often 8 GB) will not fit these stacks. On a 32 GB Mac, give the VM ~16 GB. 16 GB total
runs the lab but swaps hard the moment Immich imports while Jellyfin transcodes.
🐧 On Linux there is no VM and no fixed allocation: containers use host RAM directly and give it
back. The same workload fits comfortably in ~4 GB less.

**Disk.** Beyond images (immich-ml ~4 GB, home-assistant ~2 GB, jellyfin ~1.5 GB, coolify ~1.5 GB,
rest smaller), the boot disk also carries:

| Path                     | Growth                                         |
| ------------------------ | ---------------------------------------------- |
| `immich-photos/db-data`  | ~1 GB per 100k assets                          |
| `immich-photos/ml-cache` | ~3 GB of downloaded models                     |
| `jellyfin/cache`         | 5–20 GB of transcode scratch                   |
| `home-assistant/config`  | 1–5 GB; the recorder DB grows continuously     |
| Docker image layers      | Coolify builds accumulate here, not on the NAS |

The smaller disk sizes are workable only if you stay on top of `docker system prune`.
🐧 On Linux that all lives under `/var/lib/docker` — give `/var` its own room, or move the
data-root with `{"data-root": "/data/docker"}` in `/etc/docker/daemon.json`.

## Platform differences

The same compose files run on both, but the machine underneath behaves quite differently. **Linux
is the better host for this lab**; macOS works and is a fine place to start.

| Capability                      | 🍎 macOS (Docker Desktop / Colima)                                                                                                    | 🐧 Linux (Docker Engine)                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| **Container runtime**           | Inside a VM — fixed RAM/CPU allocation                                                                                                | Native — containers are host processes                                                            |
| **GPU for Jellyfin**            | None. Every transcode is CPU-only; a 4K HEVC transcode is out of reach                                                                | `/dev/dri` VAAPI/QSV or NVENC. One core instead of four                                           |
| **GPU for Immich ML**           | None. First import takes hours                                                                                                        | CUDA/OpenVINO images. First import takes minutes                                                  |
| **LAN device discovery (HA)**   | Broken. The VM is NAT'd, so mDNS/SSDP/HomeKit never see your LAN — `privileged` and `NET_ADMIN` buy nothing                           | Works with `network_mode: host`                                                                   |
| **USB dongles (Zigbee/Z-Wave)** | Not passed through                                                                                                                    | `devices: /dev/serial/by-id/...`                                                                  |
| **Coolify as a PaaS**           | Installs and the UI runs, but it cannot manage the Mac — it expects to SSH into a Linux host                                          | Fully functional; give it the Docker socket                                                       |
| **Bind-mount performance**      | Through virtiofs — noticeably slower than native                                                                                      | Native filesystem speed                                                                           |
| **Image architecture**          | amd64-only images run under Rosetta with a real CPU/RAM penalty. Check with `docker image inspect <img> --format '{{.Architecture}}'` | Whatever the host is                                                                              |
| **Firewall**                    | Off by default                                                                                                                        | Usually on — allow `tailscale0` (see [SETUP.md](./SETUP.md#step-7--remote-access-over-tailscale)) |
| **Socket permissions**          | Handled by Docker Desktop                                                                                                             | Your user must be in the `docker` group                                                           |
| **Start at boot**               | Docker Desktop → General → start at login                                                                                             | `sudo systemctl enable --now docker`                                                              |
| **External storage**            | Finder mount + a Login Item; must be added to Docker Desktop's file-sharing list                                                      | `/etc/fstab` with `nofail,_netdev`                                                                |

### If you are choosing a machine

- **Any Linux box with 16 GB and an Intel iGPU** (an N100 mini PC, a used SFF desktop) runs this
  lab better than a much more expensive Mac, purely because of hardware transcoding and working
  device discovery.
- **A Mac mini** is a good host if you already have one: quiet, low-power, and everything except
  Jellyfin transcoding, Immich ML speed, HA discovery, and Coolify works exactly as intended.
- **Don't run Docker Desktop for Linux.** It puts the VM back and undoes every advantage above.
