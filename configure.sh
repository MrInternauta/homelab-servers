#!/usr/bin/env bash
#
# configure.sh — one-shot host configuration for this home lab.
#
# Works on macOS and Linux. It:
#   1. detects the OS and sensible defaults (paths, PUID/PGID)
#   2. creates the root `.env` from `.env.example` if missing
#   3. creates each service's `.env` from its `.env.example` if missing
#   4. copies the shared host settings into every service `.env`
#   5. generates any secret that is still empty
#   6. creates the host directories the bind mounts need
#
# It never overwrites a secret you already set. Re-run it any time — it is
# idempotent, and it is how you re-point the lab after moving your storage.
#
# Usage:
#   ./configure.sh            # configure everything
#   ./configure.sh --dry-run  # show what it would do, change nothing
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

DRY_RUN=0
[[ ${1:-} == "--dry-run" ]] && DRY_RUN=1

BOLD=$'\033[1m'
DIM=$'\033[2m'
RED=$'\033[31m'
GRN=$'\033[32m'
YEL=$'\033[33m'
OFF=$'\033[0m'
info() { printf '%s\n' "  $*"; }
ok() { printf '%s\n' "  ${GRN}✓${OFF} $*"; }
warn() { printf '%s\n' "  ${YEL}!${OFF} $*"; }
die() {
	printf '%s\n' "  ${RED}✗${OFF} $*" >&2
	exit 1
}
head_() { printf '\n%s\n' "${BOLD}$*${OFF}"; }

SERVICES=(audiobookshelf coolify papra-doc home-assistant jellyfin immich-photos portainer obsidian-brain)

# ── 1. Detect the platform ───────────────────────────────────────────────────
head_ "1. Platform"

OS="$(uname -s)"
case "${OS}" in
Darwin) PLATFORM=macos ;;
Linux) PLATFORM=linux ;;
*) die "Unsupported OS: ${OS} (this lab targets macOS and Linux)" ;;
esac

# first_dir <glob…> — print the first existing directory a glob matches
first_dir() {
	local d
	for d in "$@"; do
		[[ -d ${d} ]] && {
			printf '%s' "${d}"
			return 0
		}
	done
	return 0
}

case "${PLATFORM}" in
macos)
	DEF_MEDIA_ROOT="${HOME}"
	# First external volume that is not the boot disk, else a clear placeholder.
	shopt -s nullglob
	DEF_EXTERNAL_STORAGE="$(first_dir /Volumes/*)"
	[[ ${DEF_EXTERNAL_STORAGE} == "/Volumes/Macintosh HD" ]] && DEF_EXTERNAL_STORAGE=""
	shopt -u nullglob
	DEF_EXTERNAL_STORAGE="${DEF_EXTERNAL_STORAGE:-/Volumes/CHANGEME}"
	;;
linux)
	DEF_MEDIA_ROOT="${HOME}"
	shopt -s nullglob
	DEF_EXTERNAL_STORAGE="$(first_dir /mnt/* /srv/*)"
	shopt -u nullglob
	DEF_EXTERNAL_STORAGE="${DEF_EXTERNAL_STORAGE:-/mnt/CHANGEME}"
	;;
*) ;;
esac
DEF_PUID="$(id -u)"
DEF_PGID="$(id -g)"

ok "detected ${BOLD}${PLATFORM}${OFF} — uid ${DEF_PUID}, gid ${DEF_PGID}"

# ── 2. Docker sanity check ───────────────────────────────────────────────────
head_ "2. Docker"

if ! command -v docker >/dev/null 2>&1; then
	warn "docker not found — install it first, see DOCKER-INSTALL.md"
elif ! docker compose version >/dev/null 2>&1; then
	warn "the 'docker compose' plugin is missing (this repo does not use docker-compose v1)"
elif ! docker info >/dev/null 2>&1; then
	if [[ ${PLATFORM} == macos ]]; then
		warn "docker is installed but not running — start Docker Desktop / Colima"
	else
		warn "cannot talk to the Docker daemon — 'sudo systemctl start docker', and make"
		warn "sure you are in the 'docker' group (see DOCKER-INSTALL.md)"
	fi
else
	docker_v="$(docker --version)"
	compose_v="$(docker compose version --short)"
	ok "${docker_v%%,*} + compose ${compose_v}"
fi

# ── 3. helpers ───────────────────────────────────────────────────────────────

# get_env <file> <key> — print the value of KEY in a dotenv file ("" if absent)
get_env() {
	[[ -f $1 ]] || return 0
	awk -F= -v k="$2" '$1==k { sub(/^[^=]*=/,""); v=$0 } END { print v }' "$1"
}

# put_env <file> <key> <value> — set or replace KEY, preserving everything else
put_env() {
	local file="$1" key="$2" val="$3" tmp
	((DRY_RUN)) && {
		info "${DIM}would set ${key} in ${file#"${ROOT_DIR}"/}${OFF}"
		return 0
	}
	tmp="$(mktemp)"
	awk -v k="${key}" -v v="${val}" '
    $0 ~ "^[[:space:]]*"k"[[:space:]]*=" { if (!seen) { print k "=" v; seen=1 } ; next }
    { print }
    END { if (!seen) print k "=" v }
  ' "${file}" >"${tmp}"
	mv "${tmp}" "${file}"
}

# drop_env <file> <key> — remove a key entirely (used for legacy keys)
drop_env() {
	local file="$1" key="$2" tmp
	grep -qE "^[[:space:]]*${key}[[:space:]]*=" "${file}" 2>/dev/null || return 0
	((DRY_RUN)) && {
		info "${DIM}would drop legacy ${key} from ${file#"${ROOT_DIR}"/}${OFF}"
		return 0
	}
	tmp="$(mktemp)"
	grep -vE "^[[:space:]]*${key}[[:space:]]*=" "${file}" >"${tmp}"
	mv "${tmp}" "${file}"
}

# seed_secret <file> <key> <generator-command…> — fill KEY only if it is empty
seed_secret() {
	local file="$1" key="$2"
	shift 2
	local current
	current="$(get_env "${file}" "${key}")"
	[[ -n ${current} ]] && return 0
	local value
	value="$("$@")"
	put_env "${file}" "${key}" "${value}"
	((DRY_RUN)) || ok "generated ${key} for ${file#"${ROOT_DIR}"/}"
}

gen_hex() { openssl rand -hex "$1"; }
gen_appkey() {
	local raw
	raw="$(openssl rand -base64 32)"
	printf 'base64:%s' "${raw}"
}

# is_mounted <path> — true if the path is a real mount point, not a stub dir
is_mounted() {
	local p="$1"
	if [[ ${PLATFORM} == linux ]] && command -v mountpoint >/dev/null 2>&1; then
		mountpoint -q "${p}"
	else
		mount | grep -qE " on ${p} "
	fi
}

# ── 4. Root .env ─────────────────────────────────────────────────────────────
head_ "3. Root .env"

if [[ ! -f .env ]]; then
	((DRY_RUN)) || cp .env.example .env
	info "created .env from .env.example"
	for kv in "TZ=${TZ:-America/Mexico_City}" "PUID=${DEF_PUID}" "PGID=${DEF_PGID}" \
		"MEDIA_ROOT=${DEF_MEDIA_ROOT}" "EXTERNAL_STORAGE=${DEF_EXTERNAL_STORAGE}" \
		"SERVICE_HOST=127.0.0.1"; do
		((DRY_RUN)) || put_env .env "${kv%%=*}" "${kv#*=}"
	done
	ok "seeded with detected defaults"
else
	ok ".env already exists — keeping your values"
fi

if ((DRY_RUN)) && [[ ! -f .env ]]; then
	TZ_V="America/Mexico_City"
	PUID_V="${DEF_PUID}"
	PGID_V="${DEF_PGID}"
	MEDIA_ROOT_V="${DEF_MEDIA_ROOT}"
	EXTERNAL_STORAGE_V="${DEF_EXTERNAL_STORAGE}"
else
	TZ_V="$(get_env .env TZ)"
	TZ_V="${TZ_V:-America/Mexico_City}"
	PUID_V="$(get_env .env PUID)"
	PUID_V="${PUID_V:-${DEF_PUID}}"
	PGID_V="$(get_env .env PGID)"
	PGID_V="${PGID_V:-${DEF_PGID}}"
	MEDIA_ROOT_V="$(get_env .env MEDIA_ROOT)"
	EXTERNAL_STORAGE_V="$(get_env .env EXTERNAL_STORAGE)"
fi

[[ ${MEDIA_ROOT_V} == *CHANGEME* || -z ${MEDIA_ROOT_V} ]] &&
	die "MEDIA_ROOT is not set in .env — edit it, then re-run ./configure.sh"
[[ ${EXTERNAL_STORAGE_V} == *CHANGEME* || -z ${EXTERNAL_STORAGE_V} ]] &&
	die "EXTERNAL_STORAGE is not set in .env — edit it, then re-run ./configure.sh"

info "TZ               = ${TZ_V}"
info "PUID/PGID        = ${PUID_V}/${PGID_V}"
info "MEDIA_ROOT       = ${MEDIA_ROOT_V}"
info "EXTERNAL_STORAGE = ${EXTERNAL_STORAGE_V}"

# ── 5. Per-service .env ──────────────────────────────────────────────────────
head_ "4. Service .env files"

for svc in "${SERVICES[@]}"; do
	[[ -d ${svc} ]] || {
		warn "${svc}/ missing — skipped"
		continue
	}
	[[ -f "${svc}/.env.example" ]] || {
		warn "${svc}/.env.example missing — skipped"
		continue
	}

	if [[ ! -f "${svc}/.env" ]]; then
		((DRY_RUN)) || cp "${svc}/.env.example" "${svc}/.env"
		ok "created ${svc}/.env"
	fi

	# Shared host settings are always re-synced from the root .env — but only the
	# keys a given service actually declares in its .env.example.
	for kv in "TZ=${TZ_V}" "PUID=${PUID_V}" "PGID=${PGID_V}" \
		"MEDIA_ROOT=${MEDIA_ROOT_V}" "EXTERNAL_STORAGE=${EXTERNAL_STORAGE_V}"; do
		if grep -qE "^[[:space:]]*${kv%%=*}[[:space:]]*=" "${svc}/.env.example"; then
			put_env "${svc}/.env" "${kv%%=*}" "${kv#*=}"
		fi
	done
done
ok "shared host settings synced into every service .env"

# Legacy keys from the pre-cross-platform layout.
[[ -f papra-doc/.env ]] && {
	drop_env papra-doc/.env UID
	drop_env papra-doc/.env GID
}

# Coolify keeps ALL of its state in one directory. Default it to the external
# volume; a Linux host is better off pointing it at a local disk (Postgres on a
# network share is slow and fragile) — edit coolify/.env to change it.
COOLIFY_STORAGE_V=""
if [[ -f coolify/.env ]]; then
	COOLIFY_STORAGE_V="$(get_env coolify/.env COOLIFY_STORAGE)"
	if [[ -z ${COOLIFY_STORAGE_V} ]]; then
		COOLIFY_STORAGE_V="${EXTERNAL_STORAGE_V}/Storage/coolify"
		put_env coolify/.env COOLIFY_STORAGE "${COOLIFY_STORAGE_V}"
		ok "COOLIFY_STORAGE defaulted to ${COOLIFY_STORAGE_V}"
	else
		info "COOLIFY_STORAGE   = ${COOLIFY_STORAGE_V}"
	fi
fi

# ── 6. Secrets ───────────────────────────────────────────────────────────────
head_ "5. Secrets"

if ! command -v openssl >/dev/null 2>&1; then
	warn "openssl not found — fill the secrets in papra-doc/.env, immich-photos/.env"
	warn "and coolify/.env by hand (see SETUP.md § Step 3 — Configure the lab)"
else
	[[ -f papra-doc/.env ]] && seed_secret papra-doc/.env AUTH_SECRET gen_hex 32
	[[ -f immich-photos/.env ]] && seed_secret immich-photos/.env DB_PASSWORD gen_hex 24
	if [[ -f coolify/.env ]]; then
		seed_secret coolify/.env APP_ID gen_hex 16
		seed_secret coolify/.env APP_KEY gen_appkey
		seed_secret coolify/.env DB_PASSWORD gen_hex 24
		seed_secret coolify/.env REDIS_PASSWORD gen_hex 24
		seed_secret coolify/.env PUSHER_APP_ID gen_hex 16
		seed_secret coolify/.env PUSHER_APP_KEY gen_hex 24
		seed_secret coolify/.env PUSHER_APP_SECRET gen_hex 24
	fi
	ok "every secret has a value"
fi

# ── 7. Host directories ──────────────────────────────────────────────────────
head_ "6. Host directories"

make_dir() {
	if ((DRY_RUN)); then
		info "${DIM}would create $1${OFF}"
		return 0
	fi
	mkdir -p "$1"
}

for d in Audio Videos Images Documents; do make_dir "${MEDIA_ROOT_V}/${d}"; done
ok "local media dirs under ${MEDIA_ROOT_V}"

# shellcheck disable=SC2310  # is_mounted is a predicate; a false result is the point
if [[ -d ${EXTERNAL_STORAGE_V} ]] && is_mounted "${EXTERNAL_STORAGE_V}"; then
	for d in Audio Videos Images Documents; do make_dir "${EXTERNAL_STORAGE_V}/${d}"; done
	ok "external storage dirs under ${EXTERNAL_STORAGE_V}"
else
	warn "${EXTERNAL_STORAGE_V} is NOT a mounted volume."
	warn "Mount it BEFORE starting any stack — otherwise Docker creates an empty"
	warn "directory there and Coolify's Postgres initialises a blank database."
	warn "See SETUP.md § Step 2 — Mount the external storage."
fi

if [[ -n ${COOLIFY_STORAGE_V} ]]; then
	for d in ssh applications databases services backups postgres redis; do
		make_dir "${COOLIFY_STORAGE_V}/${d}"
	done
	ok "coolify state dirs under ${COOLIFY_STORAGE_V}"
fi

# ── 8. Summary ───────────────────────────────────────────────────────────────
head_ "Done"

if ((DRY_RUN)); then
	info "dry run — nothing was written"
else
	cat <<EOF
  Next:
    1. Confirm the external storage is mounted:  ls "${EXTERNAL_STORAGE_V}"
    2. Bring the lab up:                          ./restart-all.sh
    3. Health-check it:                           ./test-services.sh

  Platform notes for ${PLATFORM}: see SETUP.md.
EOF
fi
