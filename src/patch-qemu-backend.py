#!/usr/bin/env python3
"""patch-qemu-backend.py — idempotent Qemu.pm patch for PVE 9.2.11.
Adds GET {vmid}/vgpu-info (VM.Audit, proxyto node): vGPU profile + per-VM VRAM
for VMs with an mdev/hostpci mapping, {present:0} otherwise. Never touches pools/disks.
Usage: patch-qemu-backend.py [--check-only|--apply]
"""
import sys, pathlib
P = pathlib.Path("/usr/share/perl5/PVE/API2/Qemu.pm")
METHOD_ANCHOR = "__PACKAGE__->register_method({\n    name => 'rrd',\n    path => '{vmid}/rrd',"

METHOD_BLOCK = r'''
__PACKAGE__->register_method({
    name => 'vgpu_info',
    path => '{vmid}/vgpu-info',
    method => 'GET',
    proxyto => 'node',
    permissions => {
        check => ['perm', '/vms/{vmid}', ['VM.Audit']],
    },
    description => "Read vGPU profile and per-VM VRAM usage (present=0 when the VM has no vGPU)",
    parameters => {
        additionalProperties => 0,
        properties => {
            node => get_standard_option('pve-node'),
            vmid => get_standard_option('pve-vmid'),
        },
    },
    returns => { type => 'object' },
    code => sub {
        my ($param) = @_;
        my $vmid = $param->{vmid};
        my $res = { present => 0 };
        eval {
            # COMPACT-LABEL-v1.1.2 (guest page one-liner: name + size + usage only)
            my $confpath = "/etc/pve/qemu-server/${vmid}.conf";
            return $res unless -f $confpath;
            my $conf = PVE::Tools::file_get_contents($confpath);
            my ($mdevtype) = $conf =~ /hostpci\d+:.*mdev=([\w-]+)/;
            return $res unless $mdevtype;
            my ($vmname) = $conf =~ /^name:\s*(\S+)/m;
            $res->{present} = 1;
            $res->{type} = $mdevtype;
            # live per-VM usage from enhanced collector (matched by mdev type, then VM name)
            my $livef = '/run/pve-enhanced-live.json';
            if (-f $livef) {
                my $j = eval { JSON::decode_json(PVE::Tools::file_get_contents($livef)) };
                if (ref($j) eq 'HASH' && ref($j->{vgpulist}) eq 'ARRAY') {
                    my ($hit);
                    for my $e (@{$j->{vgpulist}}) {
                        next unless ref($e) eq 'HASH';
                        if (defined($e->{type}) && $e->{type} eq $mdevtype) { $hit = $e; last; }
                    }
                    if (!$hit && defined($vmname)) {
                        for my $e (@{$j->{vgpulist}}) {
                            next unless ref($e) eq 'HASH';
                            if (defined($e->{vm}) && $e->{vm} eq $vmname) { $hit = $e; last; }
                        }
                    }
                    # NOTE: no single-entry fallback here — an entry belonging to a
                    # different VM must never be attributed to this one (e.g. stopped
                    # VMs). Unmatched VMs fall through to the sysfs profile below.
                    if ($hit) {
                        # compact one-line guest label: name + size + usage only
                        # (no [type] tag, no VM name — it's that VM's own page)
                        my $nm = (defined($hit->{name}) && $hit->{name} ne '') ? $hit->{name} : $mdevtype;
                        my ($tu, $tt);
                        if (defined($hit->{fb_total_mib}) && $hit->{fb_total_mib} =~ /^[\d.]+$/) {
                            $tt = sprintf('%.1f', $hit->{fb_total_mib} / 1024);
                        }
                        if (defined($hit->{fb_used_mib}) && $hit->{fb_used_mib} =~ /^[\d.]+$/) {
                            $tu = sprintf('%.1f', $hit->{fb_used_mib} / 1024);
                        }
                        my $label = $nm;
                        $label .= " ${tt}GB" if defined($tt);
                        $label .= " - ${tu}/${tt}GB" if defined($tu) && defined($tt);
                        $res->{label} = $label;
                        $res->{vm} = $hit->{vm} if defined($hit->{vm});
                        $res->{name} = $hit->{name} if defined($hit->{name});
                        $res->{mdev} = $hit->{mdev} if defined($hit->{mdev});
                        if (defined($hit->{fb_used_mib}) && $hit->{fb_used_mib} =~ /^[\d.]+$/) {
                            $res->{fb_used} = int($hit->{fb_used_mib} * 1048576);
                        }
                        if (defined($hit->{fb_total_mib}) && $hit->{fb_total_mib} =~ /^[\d.]+$/) {
                            $res->{fb_total} = int($hit->{fb_total_mib} * 1048576);
                        }
                    }
                }
            }
            # stopped-VM fallback: profile name from sysfs, no usage figures
            # (compact: name only, no [type] tag — one line on the guest page)
            if (!defined($res->{label})) {
                my @names = glob("/sys/bus/pci/devices/*/mdev_supported_types/${mdevtype}/name");
                if (@names && -f $names[0]) {
                    my $nm = eval { PVE::Tools::file_get_contents($names[0]) };
                    if (defined($nm)) {
                        chomp($nm);
                        $res->{label} = $nm if $nm ne '';
                        $res->{name} = $nm if $nm ne '';
                    }
                }
                $res->{label} //= $mdevtype;
            }
        };
        return $res;
    }});
'''

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check-only"
    t = P.read_text()
    present = "vgpu-info" in t
    anchor_ok = METHOD_ANCHOR in t
    if mode == "--check-only":
        print(f"vgpu-info present: {present}, rrd anchor found: {anchor_ok}")
        return 0 if present else 1
    if present:
        # content upgrade: replace a previous vgpu-info method with the current
        # template (e.g. pre-1.1.2 rich labels -> compact one-liners)
        start = "__PACKAGE__->register_method({\n    name => 'vgpu_info',"
        si = t.find(start)
        ei = t.find(METHOD_ANCHOR)
        if si != -1 and ei != -1 and si < ei and "COMPACT-LABEL-v1.1.2" not in t[si:ei]:
            t = t[:si] + METHOD_BLOCK.strip() + "\n\n" + t[ei:]
            P.write_text(t)
            print("Qemu.pm vgpu-info upgraded to compact labels")
        else:
            print("Qemu.pm already patched")
        return 0
    if not anchor_ok:
        print("rrd anchor missing, abort (version drift?)", file=sys.stderr); return 2
    t = t.replace(METHOD_ANCHOR, METHOD_BLOCK + "\n" + METHOD_ANCHOR, 1)
    P.write_text(t)
    print("Qemu.pm patched (vgpu-info)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
