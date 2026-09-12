#!/usr/bin/env python3
"""patch-frontend-js.py — idempotent JS patches for PVE 9.2.11.
- proxmoxlib.js: add render_node_temp / render_enhanced_watts / render_gpu_text if missing
- pvemanagerlib.js: StatusView height 350->470 + 6 rows after Manager Version + 3 history charts
Usage: patch-frontend-js.py [--check-only|--apply]
"""
import sys, pathlib
LIB = pathlib.Path("/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js")
MGR = pathlib.Path("/usr/share/pve-manager/js/pvemanagerlib.js")

RENDER_BLOCK = """
	render_node_temp: function(record) {
		if (!record || !Ext.isNumeric(record.used) || !Ext.isNumeric(record.total)) {
			return '-';
		}
		return record.used.toFixed(1) + '\\u00B0C (crit: ' + record.total.toFixed(1) + '\\u00B0C)';
	},

	render_enhanced_watts: function(value) {
		if (!Ext.isNumeric(value)) { return '-'; }
		return Number(value).toFixed(1) + ' W';
	},

	render_gpu_text: function(data) {
		if (!data) { return '-'; }
		let t = Ext.isNumeric(data.gputemp?.used) ? data.gputemp.used.toFixed(0)+'\\u00B0C' : '-';
		let u = Ext.isNumeric(data.gpuutil) ? data.gpuutil.toFixed(0)+'%' : '-';
		let p = Ext.isNumeric(data.gpupower) ? data.gpupower.toFixed(1)+'W' : '-';
		return `${t} \\u00B7 ${u} \\u00B7 ${p}`;
	},

	render_vgpu_list: function(data) {
		if (!data) { return '-'; }
		let list = data.vgpulist;
		if (!Ext.isArray(list) || !list.length) {
			return data.vgpuprofile ? Ext.htmlEncode(data.vgpuprofile) : '-';
		}
		// one rich label + usage bar per profile, room for 4 (single-profile hosts show 1)
		return list.slice(0, 4).map(function(e) {
			let label = Ext.htmlEncode(e.label || e.name || 'vGPU');
			let used = parseFloat(e.fb_used_mib), total = parseFloat(e.fb_total_mib);
			if (!isFinite(used) || !isFinite(total) || total <= 0) { return label; }
			let pct = Math.min(100, Math.max(0, (used / total) * 100));
			return label
				+ '<div style="background:#e5e5e5;border-radius:3px;height:7px;margin:3px 0 7px 0;">'
				+ '<div style="background:#115fa6;height:7px;border-radius:3px;width:' + pct.toFixed(1) + '%;"></div></div>';
		}).join('');
	},
"""

STATUS_ROWS = """\t{
\t    itemId: 'cputemp',
\t    iconCls: 'fa fa-fw fa-thermometer-half',
\t    title: gettext('CPU temp'),
\t    valueField: 'cputemp',
\t    maxField: 'cputemp',
\t    renderer: Proxmox.Utils.render_node_temp,
\t},
\t{
\t    itemId: 'gputemp',
\t    iconCls: 'fa fa-fw fa-thermometer-half',
\t    title: gettext('GPU temp'),
\t    valueField: 'gputemp',
\t    maxField: 'gputemp',
\t    renderer: Proxmox.Utils.render_node_temp,
\t},
\t{
\t    itemId: 'cpupowerw',
\t    iconCls: 'fa fa-fw fa-bolt',
\t    title: gettext('CPU package power'),
\t    printBar: false,
\t    textField: 'cpupowerw',
\t    renderer: Proxmox.Utils.render_enhanced_watts,
\t    value: '',
\t},
\t{
\t    itemId: 'gpupower',
\t    iconCls: 'fa fa-fw fa-bolt',
\t    title: gettext('GPU power'),
\t    printBar: false,
\t    textField: 'gpupower',
\t    renderer: Proxmox.Utils.render_enhanced_watts,
\t    value: '',
\t},
\t{
\t    itemId: 'dramw',
\t    iconCls: 'fa fa-fw fa-bolt',
\t    title: gettext('DRAM power'),
\t    printBar: false,
\t    textField: 'dramw',
\t    renderer: Proxmox.Utils.render_enhanced_watts,
\t    value: '',
\t},
\t{
\t    itemId: 'gpumem',
\t    iconCls: 'fa fa-fw fa-video-camera',
\t    title: gettext('GPU memory'),
\t    valueField: 'gpumem',
\t    maxField: 'gpumem',
\t    renderer: Proxmox.Utils.render_node_size_usage,
\t    value: '',
\t},
\t{
\t    itemId: 'vgpuprofile',
\t    colspan: 2,
\t    iconCls: 'fa fa-fw fa-cube',
\t    title: gettext('vGPU Profiles:'),
\t    printBar: false,
\t    multiField: true,
\t    renderer: ({ data }) => Proxmox.Utils.render_vgpu_list(data),
\t    value: '',
\t},
"""

CHARTS_BLOCK = """\t\t\t\t\t\t{
\t\t\t\t\t\t\ttitle: gettext('GPU Power / Temp / Usage (enhanced)'),
\t\t\t\t\t\t\txtype: 'proxmoxRRDChart',
\t\t\t\t\t\t\tfields: ['gpupower', 'gputemp', 'gpuutil'],
\t\t\t\t\t\t\tfieldTitles: [gettext('Power (W)'), gettext('Temp (C)'), gettext('Util (%)')],
\t\t\t\t\t\t\tstore: enhancedStore,
\t\t\t\t\t\t},
\t\t\t\t\t\t{
\t\t\t\t\t\t\ttitle: gettext('CPU Package Power (W)'),
\t\t\t\t\t\t\txtype: 'proxmoxRRDChart',
\t\t\t\t\t\t\tfields: ['cpupowerw'],
\t\t\t\t\t\t\tfieldTitles: [gettext('CPU W')],
\t\t\t\t\t\t\tstore: enhancedStore,
\t\t\t\t\t\t},
\t\t\t\t\t\t{
\t\t\t\t\t\t\ttitle: gettext('DRAM Power (W)'),
\t\t\t\t\t\t\txtype: 'proxmoxRRDChart',
\t\t\t\t\t\t\tfields: ['dramw'],
\t\t\t\t\t\t\tfieldTitles: [gettext('DRAM W')],
\t\t\t\t\t\t\tstore: enhancedStore,
\t\t\t\t\t\t},
"""

def check():
    lib = LIB.read_text(); mgr = MGR.read_text()
    print(f"render_node_temp present: {'render_node_temp' in lib}")
    print(f"render_enhanced_watts present: {'render_enhanced_watts' in lib}")
    print(f"cputemp row present: {'cputemp' in mgr and 'CPU temp' in mgr}")
    print(f"enhanced charts present: {'enhancedStore' in mgr}")
    print(f"StatusView height 470: {'height: 470' in mgr or 'height:470' in mgr}")
    ok = all(x in lib for x in ['render_node_temp','render_enhanced_watts']) and 'enhancedStore' in mgr
    return 0 if ok else 1

def apply():
    # 1) proxmoxlib.js — live anchor is 8-space 'render_node_size_usage: function (record) {' (space before paren)
    lib = LIB.read_text()
    if 'render_enhanced_watts' not in lib:
        anchor = "        render_node_size_usage: function (record) {"
        if anchor not in lib:
            print("lib anchor missing", file=sys.stderr); return 2
        lib = lib.replace(anchor, RENDER_BLOCK + "\n" + anchor, 1)
        # ensure render_node_temp exists (pve-mods parity)
        if 'render_node_temp' not in lib:
            pass  # included in block above
        LIB.write_text(lib)
        print("patched proxmoxlib.js")
    elif 'fb_used_mib' not in lib and 'render_vgpu_list' in lib:
        # v1.0.x upgrade: old list renderer (join<br>) -> per-entry bars version
        import re
        new_fn_match = re.search(r"\trender_vgpu_list: function\(data\) \{.*?\n\t\},\n", RENDER_BLOCK, re.DOTALL)
        old_fn_match = re.search(r"\trender_vgpu_list: function\(data\) \{.*?\n\t\},\n", lib, re.DOTALL)
        if new_fn_match and old_fn_match:
            lib = lib.replace(old_fn_match.group(0), new_fn_match.group(0), 1)
            LIB.write_text(lib)
            print("upgraded render_vgpu_list to per-entry bars")
        else:
            print("WARN: could not upgrade render_vgpu_list, restore+reapply recommended", file=sys.stderr)
    else:
        print("proxmoxlib.js already patched")
    # 2) pvemanagerlib.js StatusView
    mgr = MGR.read_text()
    if "alias: 'widget.pveNodeStatus'" in mgr:
        for old_h, new_h in [("    height: 350,", "    height: 600,"), ("    height: 470,", "    height: 600,"), ("    height: 520,", "    height: 600,"), ("    height: 550,", "    height: 600,")]:
            if old_h in mgr:
                mgr = mgr.replace(old_h, new_h, 1)
                print(f"height {old_h.strip()}->{new_h.strip()}")
                break
    # rows AFTER Manager Version item closes (not inside it): find textField pveversion, then its closing value+},
    mgr_anchor = "            textField: 'pveversion',"
    if 'CPU temp' not in mgr and mgr_anchor in mgr:
        a_idx = mgr.find(mgr_anchor)
        close_seq = "            value: '',\n        },"
        c_idx = mgr.find(close_seq, a_idx)
        if c_idx == -1:
            print("version block close not found, abort rows", file=sys.stderr); return 2
        ins = c_idx + len(close_seq)
        mgr = mgr[:ins] + "\n" + STATUS_ROWS.rstrip() + mgr[ins:]
        print("added StatusView rows")
    else:
        # v1.0.x upgrades (host already has rows): swap GPU text row -> temp bar row
        old_gpu_text = """\t{
\t    itemId: 'gputemp',
\t    iconCls: 'fa fa-fw fa-thermometer-half',
\t    title: gettext('GPU temp / util / power'),
\t    printBar: false,
\t    renderer: ({ data }) => Proxmox.Utils.render_gpu_text(data),
\t    value: '',
\t},"""
        new_gpu_bar = """\t{
\t    itemId: 'gputemp',
\t    iconCls: 'fa fa-fw fa-thermometer-half',
\t    title: gettext('GPU temp'),
\t    valueField: 'gputemp',
\t    maxField: 'gputemp',
\t    renderer: Proxmox.Utils.render_node_temp,
\t},"""
        if old_gpu_text in mgr:
            mgr = mgr.replace(old_gpu_text, new_gpu_bar, 1)
            print("upgraded GPU text row -> temp bar row")
        # v1.0.3 summed bar folded into per-entry bars: drop standalone row if present
        old_vgmem = """\t{
\t    itemId: 'vgpumem',
\t    colspan: 2,
\t    iconCls: 'fa fa-fw fa-video-camera',
\t    title: gettext('vGPU VM memory'),
\t    valueField: 'vgpumem',
\t    maxField: 'vgpumem',
\t    renderer: Proxmox.Utils.render_node_size_usage,
\t    value: '',
\t},
"""
        if old_vgmem in mgr:
            mgr = mgr.replace(old_vgmem, "", 1)
            print("removed standalone vGPU bar row (now per-entry)")
        # v1.0.3 rows lack multiField so updateField() skips them (empty row, no error):
        # mirror the stock kernel-version row pattern (multiField record renderer)
        old_vgprof = """\t    title: gettext('vGPU Profiles:'),
\t    printBar: false,
\t    renderer: ({ data }) => Proxmox.Utils.render_vgpu_list(data),"""
        new_vgprof = """\t    title: gettext('vGPU Profiles:'),
\t    printBar: false,
\t    multiField: true,
\t    renderer: ({ data }) => Proxmox.Utils.render_vgpu_list(data),"""
        if old_vgprof in mgr:
            mgr = mgr.replace(old_vgprof, new_vgprof, 1)
            print("added multiField to vGPU row")
    # charts: need model + enhancedStore def + charts after Memory Pressure Stall + start/stop hooks
    # (missing model/startUpdate = blank charts stuck at 1970 — v1.0.2 fix)
    if 'enhancedStore' not in mgr:
        model_def = """Ext.define('pve-rrd-enhanced', {
    extend: 'Ext.data.Model',
    fields: ['gputemp', 'gpuutil', 'gpupower', 'cpupowerw', 'dramw', 'cputemp',
        { type: 'date', dateFormat: 'timestamp', name: 'time' }],
});

"""
        store_anchor = "        var rrdstore = Ext.create('Proxmox.data.RRDStore', {"
        store_def = """        var enhancedStore = Ext.create('Proxmox.data.UpdateStore', {
            interval: 10000,
            autoStart: true,
            model: 'pve-rrd-enhanced',
            storeid: 'pve-enhanced-history',
            proxy: { type: 'proxmox', url: '/api2/json/nodes/' + nodename + '/enhanced-history' },
        });
"""
        if store_anchor in mgr:
            mgr = mgr.replace(store_anchor, model_def + store_def + "\n" + store_anchor, 1)
        chart_anchor = "                            title: gettext('Memory Pressure Stall'),"
        # insert AFTER the closing of that chart object: find 'store: rrdstore,' then its closing '},'
        mem_anchor = "                            fields: ['pressurememorysome', 'pressurememoryfull'],"
        if mem_anchor in mgr:
            idx = mgr.find(mem_anchor)
            nxt = mgr.find("store: rrdstore,", idx)
            if nxt != -1:
                close_idx = mgr.find("},", nxt)
                if close_idx != -1:
                    ins = close_idx + len("},")
                    mgr = mgr[:ins] + "\n" + CHARTS_BLOCK.rstrip() + mgr[ins:]
                    print("added enhanced charts")
    # Summary activate/destroy must start/stop enhancedStore (else blank charts at 1970)
    if 'enhancedStore.startUpdate()' not in mgr:
        act_old = "                    rstore.startUpdate(); // just to be sure\n                    rrdstore.startUpdate();"
        act_new = "                    rstore.startUpdate(); // just to be sure\n                    rrdstore.startUpdate();\n                    if (typeof enhancedStore !== 'undefined') { enhancedStore.startUpdate(); }"
        if act_old in mgr:
            mgr = mgr.replace(act_old, act_new, 1)
            print("hooked Summary activate")
        dest_old = "                    rrdstore.stopUpdate();"
        dest_new = "                    rrdstore.stopUpdate();\n                    if (typeof enhancedStore !== 'undefined') { enhancedStore.stopUpdate(); }"
        if dest_old in mgr:
            mgr = mgr.replace(dest_old, dest_new, 1)
            print("hooked Summary destroy")
    MGR.write_text(mgr)
    print("patched pvemanagerlib.js")
    patch_guest(mgr_path=MGR)
    return 0

GUEST_ROWS = """\t{
\t    itemId: 'vgpuprofile',
\t    iconCls: 'fa fa-video-camera fa-fw',
\t    title: gettext('vGPU:'),
\t    hidden: true,
\t    value: '',
\t},
"""

# Merged single row: profile name left-aligned, VRAM usage right-aligned, native bar below.
# (pmxInfoWidget renders {usage} unescaped, so floated divs paint natively.)
GUEST_FETCH_JS = """            if (view.pveSelNode.data.type === 'qemu') {
                var fetchVgpu = function () {
                    var nodename = view.pveSelNode.data.node;
                    var vmid = view.pveSelNode.data.vmid;
                    Proxmox.Utils.API2Request({
                        url: `/api2/extjs/nodes/${nodename}/qemu/${vmid}/vgpu-info`,
                        method: 'GET',
                        success: function (response) {
                            var d = (response.result && response.result.data) || {};
                            var profRow = view.down('#vgpuprofile');
                            if (!profRow) { return; }
                            if (d.present) {
                                profRow.setVisible(true);
                                var left = d.name || d.type || 'vGPU';
                                if (d.fb_used != null && d.fb_total) {
                                    var frac = d.fb_total > 0 ? d.fb_used / d.fb_total : 0;
                                    profRow.setPrintBar(true);
                                    profRow.updateValue(
                                        left + ' - ' + Proxmox.Utils.format_size(d.fb_used) + ' / ' + Proxmox.Utils.format_size(d.fb_total),
                                        frac,
                                    );
                                } else {
                                    profRow.setPrintBar(false);
                                    profRow.updateValue(left);
                                }
                            } else {
                                profRow.setVisible(false);
                            }
                        },
                        failure: function () {
                            var profRow = view.down('#vgpuprofile');
                            if (profRow) { profRow.setVisible(false); }
                        },
                    });
                };
                fetchVgpu();
                view.vgpuTask = Ext.TaskManager.start({ run: fetchVgpu, interval: 10000 });
                view.on('destroy', function () {
                    if (view.vgpuTask) { Ext.TaskManager.stop(view.vgpuTask); }
                });
            }
"""

def patch_guest(mgr_path):
    """Per-VM vGPU rows on GuestStatusView (QEMU only, hidden otherwise). Idempotent."""
    mgr = mgr_path.read_text()
    if "Ext.define('PVE.panel.GuestStatusView'" not in mgr:
        print("GuestStatusView missing, abort guest patch", file=sys.stderr); return 2
    guest_section = mgr.split("Ext.define('PVE.panel.GuestStatusView'")[1].split("updateTitle")[0]
    # v1.1.x upgrade: two-row layout (profile text + memory bar) -> merged single row
    old_mem_row = """\t{
\t    itemId: 'vgpumem',
\t    iconCls: 'fa fa-video-camera fa-fw',
\t    title: gettext('vGPU memory'),
\t    hidden: true,
\t    value: '',
\t},
"""
    if mgr.count(old_mem_row) == 1:
        mgr = mgr.replace(old_mem_row, "", 1)
        print("removed old guest vGPU memory row (merged)")
        guest_section = mgr.split("Ext.define('PVE.panel.GuestStatusView'")[1].split("updateTitle")[0]
    old_fetch_tail = """                            var profRow = view.down('#vgpuprofile');
                            var memRow = view.down('#vgpumem');
                            if (!profRow || !memRow) { return; }"""
    if old_fetch_tail in mgr:
        # replace whole old fetch block (memRow-based) with the merged version
        start = mgr.find("            if (view.pveSelNode.data.type === 'qemu') {")
        end_marker = """                view.on('destroy', function () {
                    if (view.vgpuTask) { Ext.TaskManager.stop(view.vgpuTask); }
                });
            }
"""
        end = mgr.find(end_marker, start)
        if start != -1 and end != -1:
            mgr = mgr[:start] + GUEST_FETCH_JS.rstrip() + mgr[end + len(end_marker):]
            print("upgraded guest vGPU fetch to merged row")
        else:
            print("WARN: old guest fetch bounds not found, left as-is", file=sys.stderr)
    elif 'float:left' in mgr:
        # v1.1.3 float layout -> plain 'name - used / total' separator (floats collapse in widget)
        # anchor BACKWARD/forward from the unique float marker so duplicate qemu-if lines elsewhere can't mislead us
        pos = mgr.find('float:left')
        start = mgr.rfind("            if (view.pveSelNode.data.type === 'qemu') {", 0, pos)
        end_marker = """                view.on('destroy', function () {
                    if (view.vgpuTask) { Ext.TaskManager.stop(view.vgpuTask); }
                });
            }
"""
        end = mgr.find(end_marker, pos)
        if start != -1 and end != -1:
            mgr = mgr[:start] + GUEST_FETCH_JS.rstrip() + mgr[end + len(end_marker):]
            print("upgraded guest vGPU fetch to plain separator")
        else:
            print("WARN: guest fetch bounds not found, left as-is", file=sys.stderr)
    # 1) rows after Bootdisk (rootfs) item
    guest_anchor = """            renderer: function (used, max) {
                var me = this;
                me.setPrintBar(used > 0);
                if (used === 0) {
                    return Proxmox.Utils.render_size(max);
                } else {
                    return Proxmox.Utils.render_size_usage(used, max);
                }
            },
        },"""
    if 'vgpuprofile' not in guest_section:
        if mgr.count(guest_anchor) != 1:
            print(f"guest rows anchor count={mgr.count(guest_anchor)}, abort guest rows", file=sys.stderr); return 2
        mgr = mgr.replace(guest_anchor, guest_anchor + "\n" + GUEST_ROWS.rstrip(), 1)
        print("added guest vGPU rows")
    else:
        print("guest vGPU rows already patched")
    # 2) controller fetch (qemu branch before lxc early-return)
    lxc_branch = """        init: function (view) {
            if (view.pveSelNode.data.type !== 'lxc') {
                return;
            }"""
    if 'vgpu-info' not in mgr and lxc_branch in mgr:
        if mgr.count(lxc_branch) != 1:
            print("guest controller anchor not unique, abort guest fetch", file=sys.stderr); return 2
        mgr = mgr.replace(
            lxc_branch,
            "        init: function (view) {\n" + GUEST_FETCH_JS.rstrip() + "\n            if (view.pveSelNode.data.type !== 'lxc') {\n                return;\n            }",
            1,
        )
        print("added guest vGPU fetch")
    elif 'vgpu-info' in mgr:
        print("guest vGPU fetch already patched")
    else:
        print("guest controller anchor missing, abort guest fetch", file=sys.stderr); return 2
    mgr_path.write_text(mgr)
    print("patched guest summary")
    return 0

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check-only"
    if mode == "--check-only": raise SystemExit(check())
    raise SystemExit(apply())
