# proxmox-summary-enhancement

PVE **Node Summary** enhancement for Proxmox VE **9.2.11** (`pve-manager 9.2.11`, `proxmox-widget-toolkit 5.2.8`):
live temps, GPU stats, CPU/DRAM power and vGPU profiles in the main status box,
plus history graphs for GPU + CPU/DRAM power underneath the stock charts.

Inspired by `alexleigh/pve-mods` (temps via `lm-sensors` → `Nodes.pm` → `pvemanagerlib.js`)
and the extended-sensors concept of `Javisen/proxmox_sensors`. This repo is a clean,
version-guarded, backup-first implementation for PVE 9.x with NVIDIA + Intel RAPL + vGPU.

> Hobby-project disclaimer (same as pve-mods): this patches files owned by
> Proxmox packages. Any `pve-manager` / `proxmox-widget-toolkit` update will
> overwrite it — just re-run `install.sh`. `uninstall.sh` restores backups.

## Screenshots

<p align="center">
  <img src="https://github.com/AncientMystic/proxmox-summary-enhancement/blob/main/screenshots/proxmox-summary-dash.JPG" alt="Node Summary status box with CPU and GPU temps, power readings and vGPU profiles list" width="850"/>
</p>

<p align="center">
  <img src="https://github.com/AncientMystic/proxmox-summary-enhancement/blob/main/screenshots/gpu-graph.JPG" alt="GPU power temperature usage history" width="850"/>
</p>

<p align="center">
  <img src="https://github.com/AncientMystic/proxmox-summary-enhancement/blob/main/screenshots/CPU-DRAWM-W-Graph.JPG" alt="CPU / DRAM Power Usage History" width="850"/>
</p>

(times displayed just the same as every other graph but removed here for privacy.)

## New Feature - Per VM vGPU info: 
<p align="center">
  <img src="https://github.com/AncientMystic/proxmox-summary-enhancement/blob/main/screenshots/per-vm-vgpu.JPG" alt="Per VM vGPU profile info" width="850"/>
</p> 

## What you get

**Status box (live, polled with node status ~1s), in this order under Manager Version:**
- `CPU temp` — bar + text, `sensors -j` `coretemp-isa-0000` → `Package id 0` → `temp1_input` (crit `temp1_crit`, 110°C on i7-7820X)
- `GPU temp` — bar + text, `nvidia-smi` `temperature.gpu` (crit 95°C). Pass-through GPUs are invisible to the host by design and correctly absent here.
- `CPU package power` — `W`, Intel RAPL `intel-rapl:0` (`package-0`) `energy_uj` delta
- `GPU power` — `W`, `nvidia-smi` `power.draw`
- `DRAM power` — `W`, Intel RAPL `intel-rapl:0:0` (`dram`) `energy_uj` delta
- `GPU memory` — bar + text in GB (MiB from `nvidia-smi` converted to bytes for the stock size renderer)
- `vGPU Profiles:` — full-width list with room for up to 4 profiles, each entry showing profile name, type, VRAM size and per-VM usage plus its own usage bar, e.g. `GRID RTX6000-12Q [nvidia-262] 12.0GB - VM 9.4/12.0GB (Win11-24H2)`. Sourced from `nvidia-smi vgpu -q` (per-VM guest FB usage) with `mdevctl`+sysfs fallback. Hosts without vGPU show `-`.
- `pm-power` note: `/usr/sbin/pcm-power` reports the same CPU+DRAM domains but needs a ~1s perf sample. The collector uses RAPL sysfs (same silicon counters, lightweight) and keeps `pcm-power` as a manual cross-check (`USE_PCM_POWER=1` env supported, see collector comments).

**History graphs (10s samples, 12h ring of 4320 points), appended after Memory Pressure Stall:**
- `GPU Power / Temp / Usage (enhanced)` — W, °C, % from `nvidia-smi`
- `CPU Package Power (W)` — RAPL package domain
- `DRAM Power (W)` — RAPL DRAM domain
- Backed by a dedicated `pve-rrd-enhanced` model + `UpdateStore` polling new API `GET /nodes/{node}/enhanced-history` every 10s (auto-started/stopped with the Summary panel). The stock `pve2-node` RRD schema is deliberately untouched — no RRD migration breakage on update.

## Requirements (host)

- Proxmox VE 9.2.11 exactly (`pveversion`, `dpkg -l pve-manager proxmox-widget-toolkit` checked by installer, aborts otherwise; `--force` to override at own risk)
- `lm-sensors` (`apt install lm-sensors`); `drivetemp` module optional for HDD temps (not used here)
- NVIDIA driver + `nvidia-smi` (GPU rows/graphs degrade to `No Data`/`-` if absent; vGPU list needs `nvidia-smi vgpu` + `mdevctl`)
- Intel RAPL: `/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj` (package) + `intel-rapl:0:0` (dram). Verified on i7-7820X/X299. If absent, power rows show `-`.
- `python3`, `systemd` (collector timer). No `jq`, no `rrdtool` changes needed.
- Hard-refresh the browser after install (Ctrl+Shift+R); very old browsers without optional-chaining (`?.`) support may not render the new rows.

Tested against:
- `i7-7820X 8c/16t / X299 / 96GB / RTX 2060 12GB vGPU (nvidia-262 / GRID RTX6000-12Q)`
- `sensors -j` (`coretemp-isa-0000` / `Package id 0`), `nvidia-smi 580.126.08`, `nvidia-smi vgpu -q` (per-VM FB), `pve-manager 9.2.11/f6997e6`, `proxmox-widget-toolkit 5.2.8`, kernel `6.17.13-6-pve`, EFI boot

## Layout

```
.
├── README.md
├── LICENSE                        # MIT for these scripts (Proxmox files stay AGPL-3.0)
├── VERSION                        # 1.0.4-pve9.2.11
├── install.sh                     # guard → backup → patch → collector+timer → restart pvedaemon+pveproxy
├── uninstall.sh                   # stop timer → restore backups → restart pvedaemon+pveproxy
├── src/
│   ├── collect-enhanced-stats.sh      # 10s sampler: sensors + nvidia-smi (+vgpu -q, all instances) + RAPL → JSON ring
│   ├── patch-backend.py               # idempotent Nodes.pm patch (live status fields + enhanced-history)
│   ├── patch-frontend-js.py           # idempotent pvemanagerlib.js + proxmoxlib.js patch
│   ├── pve-enhanced-collector.service
│   └── pve-enhanced-collector.timer   # OnBootSec=60s, every 10s (60s avoids early-boot nvidia-smi race)
└── patches/
    ├── REFERENCE-Nodes.pm.patch
    ├── REFERENCE-pvemanagerlib.js.patch
    └── REFERENCE-proxmoxlib.js.patch
```

Backups go to `/var/backups/proxmox-summary-enhancement-<timestamp>/` with originals + SHA256SUMS. Re-running `install.sh` is idempotent (already-patched blocks are skipped; versioned upgrade branches handle 350/470/520/550 heights and older row shapes).

## Install (on Proxmox host as root)

```bash
git clone <your-fork> /root/proxmox-summary-enhancement
cd /root/proxmox-summary-enhancement
chmod +x install.sh uninstall.sh src/*.sh src/*.py
./install.sh --check-only   # dry-run, prints what would change (safe, read-only)
./install.sh                # apply: backup, patch, install collector, restart daemons
systemctl status pve-enhanced-collector.timer
cat /run/pve-enhanced-live.json
# open WebUI → Node → Summary → hard-refresh (Ctrl+Shift+R)
```

What `install.sh` does, in order:
1. Version guard on `pve-manager` + `proxmox-widget-toolkit` (aborts on mismatch unless `--force`)
2. Read-only prereq probe: `sensors`, `nvidia-smi`, `python3`, RAPL package/dram, `pcm-power` presence
3. Backup the 3 target files + checksums under `/var/backups/...`
4. `patch-backend.py` → `/usr/share/perl5/PVE/API2/Nodes.pm` (live `cputemp/gputemp/gpuutil/gpupower/gpumem/cpupowerw/dramw/vgpuprofile/vgpulist` fields + `enhanced-history` method; MiB→bytes conversion for memory bars; everything `eval{}`-guarded so missing tools never break the API)
5. `patch-frontend-js.py` → `pvemanagerlib.js` (`StatusView` height 350→600, 7 rows after Manager Version, model + store + 3 charts + panel start/stop hooks) and `proxmoxlib.js` (`render_node_temp` à la pve-mods, `render_enhanced_watts`, `render_gpu_text`, `render_vgpu_list` with per-entry usage bars)
6. Collector → `/usr/local/bin/pve-enhanced-collect` + systemd service/timer, first sample immediately
7. `systemctl restart pvedaemon pveproxy` (both required: Perl API + JS). `pvestatd` is intentionally NOT restarted.

## Uninstall

```bash
./uninstall.sh --latest   # restores most recent backup, removes collector units/binary, restarts daemons
```

Collector state in `/var/lib/pve-enhanced/` is left in place on purpose (reinstalls resume history); delete manually if desired.

## How it works (so you can audit)

**Collector (`collect-enhanced-stats.sh`):** pure bash + embedded `python3` for JSON (no `jq`). Each run: `sensors -j` package temp, one `nvidia-smi --query-gpu` call (temp/util/power/mem/clocks), full `nvidia-smi vgpu -q` parse of **every** `vGPU ID` block (name, type→`nvidia-XXX` via sysfs `mdev_type` link, MDEV UUID, VM name, per-VM FB used/total) with `mdevctl`-list fallback covering all devices, RAPL package+dram watts as `Δenergy/1e6/Δt` with `max_energy_range_uj` wraparound handling (first run after boot yields `null` watts until a delta exists — by design). Writes `/run/pve-enhanced-live.json` (atomic tmp+rename) and appends to `/var/lib/pve-enhanced/history.json` trimmed to 4320 points. `USE_PCM_POWER=1` switches watts to a `pcm-power` sample with RAPL fallback.

**Backend (`Nodes.pm`):** pve-mods pattern — live values merged into `status` (`cputemp` as `{used,total}` for the temp renderer, memory figures converted to bytes, `vgpulist` array passed through plus summed `vgpumem`), plus `enhanced-history` serving the JSON ring. The API prefers the collector live file (<30s old) with direct `sensors`/`nvidia-smi`/`mdevctl` fallback; watts always come from the live file (deltas can't be computed inside a stateless request).

**Frontend:** `StatusView` rows use the same data shapes as stock widgets (`{used,total}` + size/temp renderers), so bars and thresholds behave natively. The vGPU row uses the stock multi-field record pattern (like the Kernel Version row) because `updateField` only invokes `updateValue` for `multiField`/`textField`/`valueField` rows — a renderer-only row renders empty with no error, which is why the pattern matters. History charts reuse `proxmoxRRDChart` bound to an `UpdateStore` with a proper date model (`pve-rrd-enhanced`), auto-started/stopped with the panel.

## Troubleshooting

- Rows show `-`/`No Data`: check sources in order — `sensors -j | python3 -m json.tool | grep -A5 coretemp`, `nvidia-smi --query-gpu=...`, `nvidia-smi vgpu -q | head -n 40`, `cat /sys/class/powercap/intel-rapl/intel-rapl:0/name`, `cat /run/pve-enhanced-live.json`, `journalctl -u pve-enhanced-collector --no-pager | tail`
- New rows/graphs missing after install: hard-refresh (Ctrl+Shift+R) or incognito; confirm `grep -c enhancedStore /usr/share/pve-manager/js/pvemanagerlib.js` is non-zero and `pvesh get /nodes/pve/status --output-format json | grep -o vgpulist` hits; `systemctl restart pveproxy` re-serves JS
- Graphs stuck at 1970/empty: `cat /var/lib/pve-enhanced/history.json | head -c 300` should show epoch-second `time` values; needs 2–3 timer ticks (~30s) before watts appear; check Summary `activate` hook ran (leave and re-enter the Summary tab)
- `pvedaemon` fails after patching: `perl -c /usr/share/perl5/PVE/API2/Nodes.pm` shows the line; restore from the newest `/var/backups/proxmox-summary-enhancement-*/` and report the `pve-manager` version so anchors can be updated
- Version mismatch abort: compare `pveversion` + `dpkg -l`, hand-port using `patches/REFERENCE-*.patch`, or `--force`
- `pcm-power` cross-check: `timeout 8 /usr/sbin/pcm-power 2>&1 | tail -n 30` package/DRAM watts should track RAPL within a few W

## Credits

- `alexleigh/pve-mods` (temps pattern: `%sensors_config`, `render_node_temp`, 4-file patch + backup/make flow) — reference patches in `patches/`
- `Javisen/proxmox_sensors` (extended-sensors concept: package-priority thermals, NVMe SMART, per-VM device mapping ideas)
- Proxmox VE: `pvestatd`, `PVE::RRD`, `PVE::API2::Nodes`, `proxmox-widget-toolkit` (`pmxInfoWidget`, `proxmoxRRDChart`, `UpdateStore`)

## License

MIT for these scripts/patches. Proxmox files remain under their licences (AGPL-3.0). Do not redistribute Proxmox binaries, only patches.
