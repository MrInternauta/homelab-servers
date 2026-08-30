# Hardware Requirements — Sizing the Mac mini

Approximate resource requirements for running all 8 stacks (**15 containers**) in this repo on a
single Mac mini under Docker Desktop.

> Companion docs: **[SETUP.md](./SETUP.md)** (bring-up), **[PLAN.md](./PLAN.md)** (services, ports,
> storage), `README.md`.

All RAM figures are steady-state RSS **inside the Docker VM** — they exclude macOS itself and the
Docker Desktop VM overhead. Totals for the whole machine are in [Machine totals](#machine-totals).

## Per-Service Resource Estimates

| Stack              | Containers                       | Idle RAM | Busy RAM          | CPU (busy)                        |
| ------------------ | -------------------------------- | -------- | ----------------- | --------------------------------- |
| **immich-photos**  | 4 (server, ml, db, valkey)       | ~2.5 GB  | **4–6 GB**        | 4+ cores during import            |
| **obsidian-brain** | 1 (Chromium + KasmVNC)           | ~700 MB  | 1.5–2 GB          | 1–2 cores when open               |
| **coolify**        | 4 (php-fpm, pg15, redis, soketi) | ~1 GB    | 1.5–2 GB          | 0.5 core, spikes on builds        |
| **home-assistant** | 1                                | ~500 MB  | 1–1.5 GB          | 0.3–1 core                        |
| **jellyfin**       | 1                                | ~300 MB  | +250 MB/stream    | **2–4 cores per 1080p transcode** |
| **audiobookshelf** | 1                                | ~200 MB  | 600 MB–1 GB (scan)| 0.5 core during library scan      |
| **papra-doc**      | 1                                | ~200 MB  | ~700 MB (OCR)     | 1 core during OCR                 |
| **portainer**      | 1                                | ~60 MB   | ~100 MB           | negligible                        |
| **Total**          | **15**                           | **~5.5 GB** | **10–14 GB**   | —                                 |

The two workloads that actually saturate the machine are Immich's ML pass (CLIP embeddings + face
detection across the whole library) and Jellyfin transcoding. Everything else is close to free.

## Machine Totals

| Resource      | Minimum | Recommended | Notes                                                       |
| ------------- | ------- | ----------- | ----------------------------------------------------------- |
| RAM           | 16 GB   | **32 GB**   | ~6 GB idle + ~1.5 GB VM overhead + 4–6 GB macOS             |
| CPU           | 6 cores | **8 cores** | Any M2/M4 mini idles fine; transcode/ML are the bottlenecks |
| Boot disk     | 256 GB  | **512 GB**  | Images alone are ~18–22 GB before any data                  |

**RAM.** 16 GB runs the lab but swaps hard the moment Immich imports while Jellyfin transcodes.
Docker Desktop's VM memory is a **fixed allocation** you set in its settings — the default (often
8 GB) will not fit these stacks. On a 32 GB machine, give the VM ~16 GB.

**Disk.** Beyond images (immich-ml ~4 GB, home-assistant ~2 GB, jellyfin ~1.5 GB, coolify ~1.5 GB,
rest smaller), the boot disk also carries:

| Path                        | Growth                                      |
| --------------------------- | ------------------------------------------- |
| `immich-photos/db-data`     | ~1 GB per 100k assets                       |
| `immich-photos/ml-cache`    | ~3 GB of downloaded models                  |
| `jellyfin/cache`            | 5–20 GB of transcode scratch                |
| `home-assistant/config`     | 1–5 GB, recorder DB grows continuously      |
| Docker image layers         | Coolify builds accumulate here, not the NAS |

256 GB is workable only if you stay on top of `docker system prune`.

## macOS-Specific Caveats

These change the math versus the same stacks on a Linux host.

1. **No GPU passthrough.** Docker Desktop on macOS exposes neither VideoToolbox nor Metal to
   containers, so Jellyfin transcodes purely on CPU and Immich ML runs CPU-only. Plan for
   direct-play in Jellyfin — a 4K HEVC transcode is effectively out of reach — and expect the
   first Immich import to take hours, not minutes.
2. **`privileged: true` + `NET_ADMIN` in Home Assistant buys nothing here.** The VM is NAT'd, so
   L2 discovery (mDNS, HomeKit, ESPHome auto-discovery) will not work. This is a functional limit,
   not a resource one — see [PLAN.md](./PLAN.md).
3. **`/Volumes/<EXTERNAL_STORAGE>` bind mounts go through virtiofs** — considerably slower than
   native, and they need explicit file-sharing entries in Docker Desktop. If the NAS unmounts,
   Coolify's Postgres data directory and Immich's `/mnt/external-data` vanish under running
   containers.
4. **Coolify is not supported on macOS.** It is built to manage the Docker host it runs on via
   SSH-to-localhost on a Linux server. Expect it to install but not fully function as a PaaS.
5. **Check the architecture of every image.** Anything amd64-only runs under Rosetta emulation
   with a real CPU and RAM penalty: `docker image inspect <image> --format '{{.Architecture}}'`.
