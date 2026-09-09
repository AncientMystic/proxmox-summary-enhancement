#!/usr/bin/env bash
# collect-enhanced-stats.sh — 10s sampler for proxmox-summary-enhancement
# Inputs (same commands user asked): sensors (cpu temps), nvidia-smi (gpu power+temp),
# RAPL sysfs for cpu/dram watts (same silicon as /usr/sbin/pcm-power, lightweight).
# Set USE_PCM_POWER=1 to cross-check with pcm-power instead of RAPL (slower, ~1-2s).
# Outputs: /run/pve-enhanced-live.json (live) + append to /var/lib/pve-enhanced/history.json (ring 4320)
set -uo pipefail

LIVE="/run/pve-enhanced-live.json"
HIST="/var/lib/pve-enhanced/history.json"
STATE_DIR="/run/pve-enhanced"
PREV_PKG="${STATE_DIR}/rapl-pkg.prev"
PREV_DRAM="${STATE_DIR}/rapl-dram.prev"
MAX_POINTS=4320
USE_PCM_POWER="${USE_PCM_POWER:-0}"

mkdir -p "$(dirname "$LIVE")" "$(dirname "$HIST")" "$STATE_DIR"

now="$(date +%s)"
cputemp="U"; cpucrit=110
gputemp="U"; gpuutil="U"; gpupower="U"; gpumemused="U"; gpumemtotal="U"; gpuclocks="U"
cpupowerw="U"; dramw="U"

# --- CPU temp via sensors -j (i7-7820X: coretemp-isa-0000 / Package id 0 / temp1_input) ---
if command -v sensors >/dev/null 2>&1; then
  sj="$(sensors -j 2>/dev/null || true)"
  if [ -n "$sj" ]; then
    read_vals="$(printf '%s' "$sj" | python3 -c 'import json,sys; d=json.load(sys.stdin); p=d.get("coretemp-isa-0000",{}).get("Package id 0",{}); print(str(p.get("temp1_input","U"))+" "+str(p.get("temp1_crit",110)))' 2>/dev/null || echo 'U 110')"
    cputemp="$(echo "$read_vals" | awk '{print $1}')"; cpucrit="$(echo "$read_vals" | awk '{print $2}')"
  fi
fi

# --- GPU via nvidia-smi (single call, cached by API layer too) ---
if command -v nvidia-smi >/dev/null 2>&1; then
  # temp, util, power, mem.used, mem.total, clocks.gr — nounits for math
  q="$(nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,power.draw,memory.used,memory.total,clocks.gr --format=csv,noheader,nounits 2>/dev/null | head -n1 || true)"
  if [ -n "$q" ]; then
    # q like: 44, 0, 22.56, 12263, 12288, 810  (power may be [N/A] when idle on vGPU)
    gputemp="$(echo "$q" | awk -F', *' '{print $1}')"; gpuutil="$(echo "$q" | awk -F', *' '{print $2}')"
    gpupower="$(echo "$q" | awk -F', *' '{print $3}')"; gpumemused="$(echo "$q" | awk -F', *' '{print $4}')"
    gpumemtotal="$(echo "$q" | awk -F', *' '{print $5}')"; gpuclocks="$(echo "$q" | awk -F', *' '{print $6}')"
    for v in gputemp gpuutil gpupower gpumemused gpumemtotal gpuclocks; do
      eval "val=\$$v"; case "$val" in "[N/A]"|"N/A"|"") eval "$v=U";; esac
    done
  fi
fi

rapl_watts() {
  # $1 = energy file, $2 = prev file, $3 = max_range file (optional)
  local ef="$1" pf="$2" mf="${3:-}" now_e prev_e prev_t max_e dt dE
  [ -f "$ef" ] || { echo U; return; }
  now_e="$(cat "$ef" 2>/dev/null || echo U)"; case "$now_e" in ''|*[!0-9]*) echo U; return;; esac
  if [ ! -f "$pf" ]; then printf '%s %s\n' "$now_e" "$now" > "$pf"; echo U; return; fi
  read -r prev_e prev_t < "$pf" 2>/dev/null || { printf '%s %s\n' "$now_e" "$now" > "$pf"; echo U; return; }
  printf '%s %s\n' "$now_e" "$now" > "$pf"
  case "$prev_e" in ''|*[!0-9]*) echo U; return;; esac
  case "$prev_t" in ''|*[!0-9]*) echo U; return;; esac
  dt=$((now - prev_t)); [ "$dt" -le 0 ] && { echo U; return; }
  if [ -n "$mf" ] && [ -f "$mf" ]; then max_e="$(cat "$mf" 2>/dev/null || echo 0)"; else max_e=0; fi
  if [ "$max_e" -gt 0 ] && [ "$now_e" -lt "$prev_e" ]; then dE=$(( (max_e - prev_e) + now_e )); else dE=$((now_e - prev_e)); fi
  [ "$dE" -lt 0 ] && { echo U; return; }
  python3 -c "print(round(($dE/1e6)/$dt,2))" 2>/dev/null || echo U
}

if [ "$USE_PCM_POWER" = "1" ] && [ -x /usr/sbin/pcm-power ]; then
  # Optional cross-check path (heavy). Parses S0 package + DRAM if exposed.
  # Kept minimal: if parse fails, fall back to RAPL below.
  pcm_out="$(timeout 6 /usr/sbin/pcm-power -silent -i1 2>/dev/null | tail -n 20 || true)"
  # pcm-power silent format varies by version; try common SKX package/DRAM lines, else U
  cpupowerw="$(printf '%s' "$pcm_out" | python3 -c 'import sys,re; t=sys.stdin.read(); m=re.search(r"Package.*?(\d+\.\d+)\s*W",t); print(m.group(1) if m else "U")' 2>/dev/null || echo U)"
  dramw="U"
  if [ "$cpupowerw" = "U" ]; then
    cpupowerw="$(rapl_watts /sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj "$PREV_PKG" /sys/class/powercap/intel-rapl/intel-rapl:0/max_energy_range_uj)"
    dramw="$(rapl_watts /sys/class/powercap/intel-rapl/intel-rapl:0/intel-rapl:0:0/energy_uj "$PREV_DRAM" /sys/class/powercap/intel-rapl/intel-rapl:0/intel-rapl:0:0/max_energy_range_uj)"
  fi
else
  cpupowerw="$(rapl_watts /sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj "$PREV_PKG" /sys/class/powercap/intel-rapl/intel-rapl:0/max_energy_range_uj)"
  dramw="$(rapl_watts /sys/class/powercap/intel-rapl/intel-rapl:0/intel-rapl:0:0/energy_uj "$PREV_DRAM" /sys/class/powercap/intel-rapl/intel-rapl:0/intel-rapl:0:0/max_energy_range_uj)"
fi

# --- vGPU profiles via nvidia-smi vgpu -q (ALL instances, per-VM FB used!) with mdevctl fallback ---
# Handles multiple vGPUs: parses every vGPU block, builds VGPU_LIST_JSON array.
# Single-profile hosts get a 1-entry list (backward compatible).
vgputype="U"; vgpuname="U"; vgpuuuid="U"; vgpuprofile="U"; vgpuvm="U"; vgpufbused="U"; vgpufbtotal="U"
VGPU_LIST_JSON="[]"
if command -v nvidia-smi >/dev/null 2>&1; then
  vq="$(nvidia-smi vgpu -q 2>/dev/null || true)"
  if [ -n "$vq" ]; then
    VGPU_LIST_JSON="$(printf '%s' "$vq" | python3 -c '
import sys, json, os, re
txt = sys.stdin.read()
blocks, cur = [], {}
for line in txt.splitlines():
    s = line.strip()
    if s.startswith("vGPU ID"):
        if cur.get("name"): blocks.append(cur)
        cur = {}
    elif s.startswith("vGPU Name"): cur["name"] = s.split(":",1)[1].strip()
    elif s.startswith("vGPU Type"): cur["typenum"] = s.split(":",1)[1].strip()
    elif s.startswith("MDEV UUID"): cur["mdev"] = s.split(":",1)[1].strip()
    elif s.startswith("VM Name"): cur["vm"] = s.split(":",1)[1].strip()
    elif re.match(r"^(Total|Used|Free)\s*:", s):
        pass
    elif "FB Memory Usage" in s: cur["_fb"] = True
    m = re.match(r"^(Total|Used)\s+:\s+(\d+)", s)
    if m and cur.get("_fb"):
        cur["fb_total" if m.group(1)=="Total" else "fb_used"] = m.group(2)
        if m.group(1)=="Used": cur.pop("_fb", None)
if cur.get("name"): blocks.append(cur)
out = []
for b in blocks:
    try: tot = round(float(b.get("fb_total", 0))/1024, 1)
    except: tot = None
    try: used = round(float(b.get("fb_used", 0))/1024, 1)
    except: used = None
    mdev = b.get("mdev", "")
    mtype = ""
    if mdev:
        try: mtype = os.path.basename(os.readlink("/sys/bus/mdev/devices/" + mdev + "/mdev_type"))
        except: mtype = ""
        if not mtype and b.get("typenum"): mtype = "nvidia-" + str(b.get("typenum"))
    label = b.get("name", "vGPU")
    if mtype: label += f" [{mtype}]"
    if tot: label += f" {tot}GB"
    if used and tot: label += f" - VM {used}/{tot}GB"
    elif used: label += f" - VM {used}GB"
    if b.get("vm"): label += f" ({b.get(chr(118)+chr(109))})"
    out.append({"label": label, "name": b.get("name"), "type": mtype,
                "mdev": mdev, "vm": b.get("vm"),
                "fb_total_mib": b.get("fb_total"), "fb_used_mib": b.get("fb_used")})
print(json.dumps(out))
' 2>/dev/null || echo '[]')"
    # backward-compat singles = first entry
    _first="$(printf '%s' "$VGPU_LIST_JSON" | python3 -c 'import json,sys; a=json.load(sys.stdin); b=a[0] if a else {}; print(b.get("label","U")+"|"+str(b.get("name","U"))+"|"+str(b.get("type","U"))+"|"+str(b.get("mdev","U"))+"|"+str(b.get("vm","U"))+"|"+str(b.get("fb_used_mib","U"))+"|"+str(b.get("fb_total_mib","U")))' 2>/dev/null || echo 'U|U|U|U|U|U|U')"
    vgpuprofile="$(echo "$_first" | cut -d'|' -f1)"; vgpuname="$(echo "$_first" | cut -d'|' -f2)"
    vgputype="$(echo "$_first" | cut -d'|' -f3)"; vgpuuuid="$(echo "$_first" | cut -d'|' -f4)"
    vgpuvm="$(echo "$_first" | cut -d'|' -f5)"; vgpufbused="$(echo "$_first" | cut -d'|' -f6)"
    vgpufbtotal="$(echo "$_first" | cut -d'|' -f7)"
    for v in vgpuprofile vgpuname vgputype vgpuuuid vgpuvm vgpufbused vgpufbtotal; do
      eval "val=\$$v"; case "$val" in ""|U) eval "$v=U";; esac
    done
  fi
fi
if [ "$vgpuprofile" = "U" ] && [ -d /sys/bus/mdev/devices ] && [ -n "$(ls -A /sys/bus/mdev/devices 2>/dev/null)" ]; then
  # fallback: ALL mdevctl lines (no per-VM FB), one label per device
  VGPU_LIST_JSON="$(mdevctl list 2>/dev/null | python3 -c '
import sys, json, os
out = []
for line in sys.stdin:
    p = line.split()
    if len(p) < 3: continue
    uuid, parent, typ = p[0], p[1], p[2]
    try:
        with open(f"/sys/bus/pci/devices/{parent}/mdev_supported_types/{typ}/name") as f: nm = f.read().strip()
    except: nm = typ
    out.append({"label": f"{nm} [{typ}] ({uuid[:8]}..)", "name": nm, "type": typ, "mdev": uuid, "vm": None, "fb_total_mib": None, "fb_used_mib": None})
print(json.dumps(out))
' 2>/dev/null || echo '[]')"
  _first="$(printf '%s' "$VGPU_LIST_JSON" | python3 -c 'import json,sys; a=json.load(sys.stdin); b=a[0] if a else {}; print(b.get("label","U"))' 2>/dev/null || echo U)"
  [ -n "$_first" ] && vgpuprofile="$_first"
  if [ "$vgpuprofile" = "U" ]; then
  # last-resort single (original behavior)
  _mdev_line="$(mdevctl list 2>/dev/null | head -n1 || true)"
  if [ -n "$_mdev_line" ]; then
    vgpuuuid="$(echo "$_mdev_line" | awk '{print $1}')"
    vgpu_parent="$(echo "$_mdev_line" | awk '{print $2}')"
    vgputype="$(echo "$_mdev_line" | awk '{print $3}')"
    if [ -n "$vgpu_parent" ] && [ -n "$vgputype" ]; then
      vgpuname="$(cat "/sys/bus/pci/devices/${vgpu_parent}/mdev_supported_types/${vgputype}/name" 2>/dev/null || echo U)"
      if [ "$vgpuname" != "U" ] && [ -n "$vgpuname" ]; then
        vgpuprofile="${vgpuname} [${vgputype}]"
      elif [ "$vgputype" != "U" ]; then
        vgpuprofile="$vgputype"
      fi
    fi
  fi
    fi
fi

# --- write live + history (python for safe JSON, no jq dep) ---
export NOW="$now" CPUT="$cputemp" CPUC="$cpucrit" GPUT="$gputemp" GPUU="$gpuutil" GPUP="$gpupower" GPUMU="$gpumemused" GPUMT="$gpumemtotal" GPUC="$gpuclocks" CPUPW="$cpupowerw" DRAMPW="$dramw" VGTYPE="$vgputype" VGNAME="$vgpuname" VGUID="$vgpuuuid" VGPROF="$vgpuprofile" VGLIST="$VGPU_LIST_JSON" LIVE_F="$LIVE" HIST_F="$HIST" MAXP="$MAX_POINTS"
python3 - <<'PY'
import json, os
def num(v):
    try:
        if v in ("U", "", None, "[N/A]"): return None
        f=float(v); return f
    except: return None
def txt(v):
    return None if v in ("U", "", None) else str(v)
now=int(os.environ["NOW"])
live={
 "time": now,
 "cputemp": num(os.environ["CPUT"]), "cpucrit": num(os.environ["CPUC"]) or 110,
 "gputemp": num(os.environ["GPUT"]), "gpuutil": num(os.environ["GPUU"]),
 "gpupower": num(os.environ["GPUP"]), "gpumemused": num(os.environ["GPUMU"]),
 "gpumemtotal": num(os.environ["GPUMT"]), "gpuclocks": num(os.environ["GPUC"]),
 "cpupowerw": num(os.environ["CPUPW"]), "dramw": num(os.environ["DRAMPW"]),
 "vgputype": txt(os.environ.get("VGTYPE")), "vgpuname": txt(os.environ.get("VGNAME")),
 "vgpuuuid": txt(os.environ.get("VGUID")), "vgpuprofile": txt(os.environ.get("VGPROF")),
 "vgpulist": json.loads(os.environ.get("VGLIST") or "[]"),
}
open(os.environ["LIVE_F"]+".tmp","w").write(json.dumps(live)+"\n")
os.replace(os.environ["LIVE_F"]+".tmp", os.environ["LIVE_F"])
hf=os.environ["HIST_F"]; maxp=int(os.environ["MAXP"])
try: arr=json.load(open(hf)) if os.path.exists(hf) else []
except: arr=[]
if not isinstance(arr, list): arr=[]
arr.append(live)
if len(arr)>maxp: arr=arr[-maxp:]
open(hf+".tmp","w").write(json.dumps(arr))
os.replace(hf+".tmp", hf)
PY
chmod 0644 "$LIVE" "$HIST" 2>/dev/null || true
