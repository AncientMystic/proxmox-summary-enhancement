#!/usr/bin/env bash
# install.sh — proxmox-summary-enhancement for PVE 9.2.11
# Version-guarded, backup-first, idempotent. Does NOT touch pools/disks.
# Usage: ./install.sh [--check-only] [--force]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_ROOT="/var/backups/proxmox-summary-enhancement"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${BACKUP_ROOT}-${STAMP}"
CHECK_ONLY=0
FORCE=0
for a in "$@"; do case "$a" in --check-only) CHECK_ONLY=1;; --force) FORCE=1;; *) echo "unknown arg $a" >&2; exit 2;; esac; done

need_root() { if [ "$(id -u)" -ne 0 ]; then echo "run as root" >&2; exit 1; fi; }
have() { command -v "$1" >/dev/null 2>&1; }

EXPECTED_PVE="9.2.11"
EXPECTED_PVEMGR="9.2.11"
EXPECTED_PWT="5.2.8"

echo "== proxmox-summary-enhancement install (${STAMP}) =="
need_root

echo "-- version guard --"
PVE_VER="$(pveversion 2>/dev/null | head -n1 || true)"
echo "pveversion: ${PVE_VER}"
PVEMGR_VER="$(dpkg-query -W -f='${Version}' pve-manager 2>/dev/null || echo unknown)"
PWT_VER="$(dpkg-query -W -f='${Version}' proxmox-widget-toolkit 2>/dev/null || echo unknown)"
echo "pve-manager: ${PVEMGR_VER}"
echo "proxmox-widget-toolkit: ${PWT_VER}"
if [ "$FORCE" -eq 0 ]; then
  case "${PVEMGR_VER}" in 9.2.11*) ;; *) echo "ABORT: pve-manager ${PVEMGR_VER} != ${EXPECTED_PVEMGR} (use --force to override, then hand-port REFERENCE patches)" >&2; exit 3;; esac
  case "${PWT_VER}" in 5.2.8*) ;; *) echo "ABORT: proxmox-widget-toolkit ${PWT_VER} != ${EXPECTED_PWT}" >&2; exit 3;; esac
else
  echo "WARN: --force, skipping version abort"
fi

TARGETS=(
  "/usr/share/perl5/PVE/API2/Nodes.pm"
  "/usr/share/pve-manager/js/pvemanagerlib.js"
  "/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
)
for f in "${TARGETS[@]}"; do [ -f "$f" ] || { echo "missing $f" >&2; exit 4; }; done
have python3 || { echo "need python3" >&2; exit 5; }

echo "-- prereqs (read-only check) --"
for c in sensors nvidia-smi python3 systemctl; do have "$c" && echo "ok $c" || echo "missing $c (GPU rows will show No Data if nvidia-smi absent; apt install lm-sensors if sensors absent)"; done
[ -f /sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj ] && echo "ok RAPL package" || echo "WARN: no RAPL package energy_uj (power rows will show -)"
[ -f /sys/class/powercap/intel-rapl/intel-rapl:0/intel-rapl:0:0/energy_uj ] && echo "ok RAPL dram" || echo "WARN: no RAPL dram energy_uj"
[ -x /usr/sbin/pcm-power ] && echo "ok pcm-power present (optional cross-check only, collector uses RAPL)" || echo "info: no pcm-power (fine, RAPL used)"

if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "-- check-only: would backup to ${BACKUP_DIR}, patch 3 files, install collector+timer, restart pvedaemon+pveproxy --"
  echo "[backend]"
  python3 "${REPO_DIR}/src/patch-backend.py" --check-only || echo "(backend not yet patched - expected before install)"
  echo "[frontend]"
  python3 "${REPO_DIR}/src/patch-frontend-js.py" --check-only || echo "(frontend not yet patched - expected before install)"
  exit 0
fi

echo "-- backup to ${BACKUP_DIR} --"
mkdir -p "${BACKUP_DIR}"
for f in "${TARGETS[@]}"; do
  mkdir -p "${BACKUP_DIR}$(dirname "$f")"
  cp -a "$f" "${BACKUP_DIR}${f}"
done
sha256sum "${TARGETS[@]}" | tee "${BACKUP_DIR}/SHA256SUMS"
cp -a "${REPO_DIR}/VERSION" "${BACKUP_DIR}/" 2>/dev/null || true
echo "backup done"

echo "-- patch backend --"
python3 "${REPO_DIR}/src/patch-backend.py" --apply

echo "-- patch frontend --"
python3 "${REPO_DIR}/src/patch-frontend-js.py" --apply

echo "-- install collector --"
mkdir -p /var/lib/pve-enhanced /run/pve-enhanced
install -m 0755 "${REPO_DIR}/src/collect-enhanced-stats.sh" /usr/local/bin/pve-enhanced-collect
install -m 0644 "${REPO_DIR}/src/pve-enhanced-collector.service" /etc/systemd/system/pve-enhanced-collector.service
install -m 0644 "${REPO_DIR}/src/pve-enhanced-collector.timer" /etc/systemd/system/pve-enhanced-collector.timer
systemctl daemon-reload
systemctl enable --now pve-enhanced-collector.timer
# immediate first sample (60s wait is in timer OnBootSec, not here)
/usr/local/bin/pve-enhanced-collect || true
ls -l /var/lib/pve-enhanced/ /run/pve-enhanced/ || true

echo "-- restart pvedaemon + pveproxy (both required: Perl API + JS) --"
systemctl restart pvedaemon.service
systemctl restart pveproxy.service
echo "NOTE: pvestatd NOT restarted (not needed). Hard-refresh browser Ctrl+Shift+R."
echo "Verify: cat /var/lib/pve-enhanced/history.json | head; journalctl -u pve-enhanced-collector --no-pager | tail"
echo "Uninstall: ./uninstall.sh --latest"
