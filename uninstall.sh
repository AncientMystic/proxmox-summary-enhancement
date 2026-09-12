#!/usr/bin/env bash
# uninstall.sh — restore most recent backup, disable collector, restart pveproxy
set -euo pipefail
MODE="${1:-}"
BACKUP_ROOT_GLOB="/var/backups/proxmox-summary-enhancement-*"
if [ "$(id -u)" -ne 0 ]; then echo "run as root" >&2; exit 1; fi
LATEST="$(ls -dt ${BACKUP_ROOT_GLOB} 2>/dev/null | head -n1 || true)"
if [ -z "${LATEST}" ]; then echo "no backup found at ${BACKUP_ROOT_GLOB}" >&2; exit 2; fi
if [ "${MODE}" != "--latest" ]; then echo "usage: $0 --latest  (would restore ${LATEST})" >&2; exit 2; fi
echo "restoring from ${LATEST}"
for f in "/usr/share/perl5/PVE/API2/Nodes.pm" "/usr/share/perl5/PVE/API2/Qemu.pm" "/usr/share/pve-manager/js/pvemanagerlib.js" "/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"; do
  if [ -f "${LATEST}${f}" ]; then cp -a "${LATEST}${f}" "$f"; echo "restored $f"; else echo "WARN missing in backup: $f"; fi
done
systemctl disable --now pve-enhanced-collector.timer 2>/dev/null || true
systemctl disable --now pve-enhanced-collector.service 2>/dev/null || true
rm -f /etc/systemd/system/pve-enhanced-collector.service /etc/systemd/system/pve-enhanced-collector.timer
rm -f /usr/local/bin/pve-enhanced-collect
systemctl daemon-reload
systemctl restart pvedaemon.service
systemctl restart pveproxy.service
echo "done. Backups kept at ${LATEST}. Collector state left at /var/lib/pve-enhanced (remove manually if desired)."
