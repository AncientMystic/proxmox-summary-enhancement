#!/usr/bin/env python3
"""patch-backend.py — idempotent Nodes.pm patch for PVE 9.2.11.
Adds live cputemp/gputemp/gpuutil/gpupower/cpupowerw/dramw to status
+ new enhanced-history method. Never touches pools/disks.
Usage: patch-backend.py [--check-only|--apply]
"""
import sys, pathlib
P = pathlib.Path("/usr/share/perl5/PVE/API2/Nodes.pm")
MARK = "# >>> pve-enhanced-sensors BEGIN"
ENDMARK = "# <<< pve-enhanced-sensors END"

BACKEND_BLOCK = r'''
# >>> pve-enhanced-sensors BEGIN (v1.0.0-pve9.2.11, idempotent)
# Live temps/power for Node Summary. All eval-guarded, missing tools -> U.
my %enhanced_sensors_config = (
    cputemp => { jsonpath => ['coretemp-isa-0000', 'Package id 0'], valkey => 'temp1_input', critkey => 'temp1_crit', defcrit => 110 },
);
my $enhanced_live_file = '/run/pve-enhanced-live.json';
my $enhanced_cache = '/run/pve-enhanced-status.cache';
my $enhanced_cache_ttl = 5;
sub _enhanced_read_live {
    my ($now) = @_; $now //= time();
    # 1) prefer collector live file (RAPL watts already computed, 10s cadence)
    if (-f $enhanced_live_file) {
        my $age = $now - (stat($enhanced_live_file))[9];
        if ($age >= 0 && $age < 30) {
            eval { require JSON; my $j = JSON::decode_json(PVE::Tools::file_get_contents($enhanced_live_file)); return $j if ref($j) eq 'HASH'; };
        }
    }
    # 2) fast fallback: direct sensors + nvidia-smi + RAPL prev files (no sleep)
    my %o = ();
    eval {
        require JSON;
        my $sj = `sensors -j 2>/dev/null`;
        my $s = JSON::decode_json($sj) if $sj;
        if ($s) {
            my $p = $s->{'coretemp-isa-0000'}->{'Package id 0'} // undef;
            $o{cputemp} = $p->{'temp1_input'}+0 if defined($p) && defined($p->{'temp1_input'});
            $o{cpucrit} = $p->{'temp1_crit'}+0 if defined($p) && defined($p->{'temp1_crit'});
        }
    };
    eval {
        my $q = `nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,power.draw,memory.used,memory.total,clocks.gr --format=csv,noheader,nounits 2>/dev/null`;
        if ($q && $q !~ /No devices|not found/i) {
            my @f = split(/\s*,\s*/, (split(/\n/, $q))[0]);
            $o{gputemp}=$f[0]+0 if defined($f[0]) && $f[0] =~ /[\d.]/;
            $o{gpuutil}=$f[1]+0 if defined($f[1]) && $f[1] =~ /[\d.]/;
            $o{gpupower}=$f[2]+0 if defined($f[2]) && $f[2] =~ /[\d.]/;
            $o{gpumemused}=$f[3]+0 if defined($f[3]) && $f[3] =~ /[\d.]/;
            $o{gpumemtotal}=$f[4]+0 if defined($f[4]) && $f[4] =~ /[\d.]/;
            $o{gpuclocks}=$f[5]+0 if defined($f[5]) && $f[5] =~ /[\d.]/;
        }
    };
    # RAPL watts need delta; without collector we return U (avoid sleep in API)
    # vGPU fallback (collector preferred): single mdevctl + sysfs name read
    eval {
        my $ml = `mdevctl list 2>/dev/null`;
        if ($ml && $ml =~ /(\S+)\s+(\S+)\s+(\S+)/) {
            my ($uuid, $parent, $type) = ($1, $2, $3);
            $o{vgpuuuid} = $uuid; $o{vgputype} = $type;
            my $nf = "/sys/bus/pci/devices/$parent/mdev_supported_types/$type/name";
            if (-f $nf) {
                my $nm = `cat $nf 2>/dev/null`; chomp($nm);
                $o{vgpuname} = $nm if $nm;
                $o{vgpuprofile} = "$nm [$type]" if $nm;
            } else { $o{vgpuprofile} = $type; }
        }
    };
    return \%o;
}
# <<< pve-enhanced-sensors END
'''

STATUS_HOOK = r'''
	# >>> pve-enhanced-sensors STATUS HOOK
	eval {
	    my $live = _enhanced_read_live(time());
	    # cputemp as {used,total} to match pve-mods renderers
	    if (defined($live->{cputemp})) {
		$res->{cputemp} = { used => $live->{cputemp}+0, total => ($live->{cpucrit} // 110)+0 };
	    } else {
		# sensors_config fallback (same as pve-mods)
		eval { require JSON; my $sensors = JSON::decode_json(`sensors -j`); my $p = $sensors->{'coretemp-isa-0000'}->{'Package id 0'}; $res->{cputemp} = { used => $p->{'temp1_input'}+0, total => ($p->{'temp1_crit'} // 110)+0 } if $p && defined($p->{'temp1_input'}); };
	    }
    $res->{gputemp} = { used => $live->{gputemp}+0, total => 95+0 } if defined($live->{gputemp});
    $res->{gpuutil} = $live->{gpuutil}+0 if defined($live->{gpuutil});
    $res->{gpupower} = $live->{gpupower}+0 if defined($live->{gpupower});
    $res->{gpumemused} = $live->{gpumemused}+0 if defined($live->{gpumemused});
    $res->{gpumemtotal} = $live->{gpumemtotal}+0 if defined($live->{gpumemtotal});
    # VGPU_BYTES_FIX v1.0.1: nvidia-smi reports MiB, render_node_size_usage expects bytes
    $res->{gpumem} = { used => int($live->{gpumemused}*1048576), total => int($live->{gpumemtotal}*1048576) } if defined($live->{gpumemused}) && defined($live->{gpumemtotal});
    $res->{gpuclocks} = $live->{gpuclocks}+0 if defined($live->{gpuclocks});
    # vGPU profile (only if mdev enabled, else keys absent and row shows '-')
    $res->{vgpuprofile} = $live->{vgpuprofile} if defined($live->{vgpuprofile});
    $res->{vgpuuuid} = $live->{vgpuuuid} if defined($live->{vgpuuuid});
    $res->{vgputype} = $live->{vgputype} if defined($live->{vgputype});
    # watts + vGPU identity from collector live file directly (RAPL deltas + vgpu -q
    # parsing already done there; helper fallback only has short "Name [type]")
    # vgpulist = full array for multi-vGPU hosts (room for 3-4); vgpuprofile kept as first-entry string
    if (-f '/run/pve-enhanced-live.json') {
	eval { require JSON; my $j = JSON::decode_json(PVE::Tools::file_get_contents('/run/pve-enhanced-live.json')); $res->{cpupowerw} = $j->{cpupowerw}+0 if defined($j->{cpupowerw}); $res->{dramw} = $j->{dramw}+0 if defined($j->{dramw}); $res->{vgpuprofile} = $j->{vgpuprofile} if defined($j->{vgpuprofile}); $res->{vgpuuuid} = $j->{vgpuuuid} if defined($j->{vgpuuuid}); $res->{vgputype} = $j->{vgputype} if defined($j->{vgputype}); $res->{vgpuname} = $j->{vgpuname} if defined($j->{vgpuname}); $res->{vgpulist} = $j->{vgpulist} if ref($j->{vgpulist}) eq 'ARRAY'; if (ref($j->{vgpulist}) eq 'ARRAY' && @{$j->{vgpulist}}) { my ($vu,$vt)=(0,0); for my $e (@{$j->{vgpulist}}) { $vu += $e->{fb_used_mib}*1048576 if defined($e->{fb_used_mib}) && $e->{fb_used_mib} =~ /^[\d.]+$/; $vt += $e->{fb_total_mib}*1048576 if defined($e->{fb_total_mib}) && $e->{fb_total_mib} =~ /^[\d.]+$/; } $res->{vgpumem} = { used => int($vu), total => int($vt) } if $vt > 0; } };
    }
	};
	# <<< pve-enhanced-sensors STATUS HOOK END
'''

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check-only"
    t = P.read_text()
    already_backend = MARK in t
    already_hook = "pve-enhanced-sensors STATUS HOOK" in t
    # anchor: 8-space 'return $res;' closing status method (PVE 9.2.11, NOT tab)
    anchor = "        return $res;"
    if mode == "--check-only":
        print(f"backend block present: {already_backend}, status hook present: {already_hook}")
        print(f"anchor found: {anchor in t}")
        return 0 if (already_backend and already_hook) else 1
    if not already_backend:
        if anchor not in t:
            print("anchor not found, abort (version drift?)", file=sys.stderr); return 2
        # insert helper subs before the *method* register (4-space indent), NOT the search-list entry
        netstat_anchor = "__PACKAGE__->register_method({\n    name => 'netstat',"
        if netstat_anchor not in t:
            print("netstat anchor missing", file=sys.stderr); return 2
        t = t.replace(netstat_anchor, BACKEND_BLOCK + "\n__PACKAGE__->register_method({\n    name => 'netstat',", 1)
    if "pve-enhanced-sensors STATUS HOOK" not in t:
        if anchor not in t:
            print("status return anchor missing", file=sys.stderr); return 2
        t = t.replace(anchor, STATUS_HOOK + "\n" + anchor, 1)
    # enhanced-history method: append before netstat method if missing
    if "enhanced-history" not in t:
        hist = r'''
__PACKAGE__->register_method({
    name => 'enhanced_history',
    path => 'enhanced-history',
    method => 'GET',
    permissions => { check => ['perm', '/nodes/{node}', ['Sys.Audit']] },
    description => "Enhanced sensors history (GPU/CPU/DRAM, 10s ring)",
    proxyto => 'node',
    parameters => { additionalProperties => 0, properties => { node => { type => 'string' } } },
    returns => { type => "array" },
    code => sub {
        my ($param) = @_;
        my $f = '/var/lib/pve-enhanced/history.json';
        return [] unless -f $f;
        my $c = eval { PVE::Tools::file_get_contents($f) } // '[]';
        my $a = eval { JSON::decode_json($c) } // [];
        # last 360 points (1h at 10s) to keep payload small; ?full=1 for all
        return $a;
    }});
'''
        t = t.replace("__PACKAGE__->register_method({\n    name => 'netstat'", hist + "\n__PACKAGE__->register_method({\n    name => 'netstat'", 1)
    elif "ENH-HIST-V2-TIMEFRAME" not in t:
        # v2: windowed + bucket-averaged + numerics-only (mirrors rrddata behaviour,
        # fixes blank charts from multi-MB full-ring payloads)
        start = "__PACKAGE__->register_method({\n    name => 'enhanced_history',"
        si = t.find(start)
        ei = t.find("__PACKAGE__->register_method({\n    name => 'netstat'")
        if si != -1 and ei != -1 and si < ei:
            hist2 = r'''
__PACKAGE__->register_method({
    name => 'enhanced_history',
    path => 'enhanced-history',
    method => 'GET',
    permissions => { check => ['perm', '/nodes/{node}', ['Sys.Audit']] },
    description => "Enhanced sensors history (GPU/CPU/DRAM, windowed + downsampled like rrddata)",
    proxyto => 'node',
    parameters => {
        additionalProperties => 0,
        properties => {
            node => get_standard_option('pve-node'),
            timeframe => {
                description => "Window like rrddata (hour/day/week/month/year)",
                type => 'string',
                enum => ['hour', 'day', 'week', 'month', 'year'],
                optional => 1,
            },
        },
    },
    returns => { type => "array" },
    code => sub {
        my ($param) = @_;
        # ENH-HIST-V2-TIMEFRAME
        my %win = (hour => 3700, day => 90000, week => 700000, month => 3100000, year => 32000000);
        my $tf = $param->{timeframe} // 'day';
        my $cut = time() - ($win{$tf} // $win{day});
        my $f = '/var/lib/pve-enhanced/history.json';
        return [] unless -f $f;
        # V3-UNCAPPED-READ: PVE::Tools::file_get_contents caps at 1MB (pmxcfs
        # limit) and dies on our multi-MB ring, which eval-swallowed to [].
        # Slurp directly with no cap instead.
        my $c = eval { open my $fh, '<', $f or die $!; local $/; my $d = <$fh>; close $fh; $d } // '[]';
        my $a = eval { JSON::decode_json($c) } // [];
        $a = [] unless ref($a) eq 'ARRAY';
        my @nums = qw(cputemp gputemp gpuutil gpupower cpupowerw dramw);
        my @pts;
        for my $p (@$a) {
            next unless ref($p) eq 'HASH' && defined($p->{time}) && $p->{time} >= $cut;
            my %o = (time => int($p->{time}));
            for my $k (@nums) {
                my $v = $p->{$k};
                $o{$k} = (defined($v) && "$v" =~ /^-?[\d.]+$/) ? $v + 0 : undef;
            }
            push @pts, \%o;
        }
        if (@pts > 800) {
            my $per = int(@pts / 800) + 1;
            my @avg;
            for (my $i = 0; $i < @pts; $i += $per) {
                my $e = $i + $per - 1;
                $e = $#pts if $e > $#pts;
                my ($n, $tsum) = (0, 0);
                my (%ssum, %cnt);
                for my $q (@pts[$i .. $e]) {
                    $n++; $tsum += $q->{time};
                    for my $k (@nums) {
                        if (defined($q->{$k})) { $ssum{$k} += $q->{$k}; $cnt{$k}++; }
                    }
                }
                my %o = (time => int($tsum / $n));
                for my $k (@nums) { $o{$k} = $cnt{$k} ? $ssum{$k} / $cnt{$k} : undef; }
                push @avg, \%o;
            }
            @pts = @avg;
        }
        return \@pts;
    }});
'''
            t = t[:si] + hist2.strip() + "\n\n" + t[ei:]
            print("upgraded enhanced-history to v2 (windowed)")
        else:
            print("WARN: enhanced-history bounds not found", file=sys.stderr)
    if "ENH-HIST-V2-TIMEFRAME" in t and "V3-UNCAPPED-READ" not in t:
        # v3: the history method reads via PVE::Tools::file_get_contents, which
        # caps at 1MB and dies on our multi-MB ring (eval-swallowed to []).
        old_read = "        my $c = eval { PVE::Tools::file_get_contents($f) } // '[]';"
        new_read = "        my $c = eval { open my $fh, '<', $f or die $!; local $/; my $d = <$fh>; close $fh; $d } // '[]';  # V3-UNCAPPED-READ"
        if t.count(old_read) == 1:
            t = t.replace(old_read, new_read, 1)
            print("upgraded enhanced-history to v3 (uncapped read)")
        else:
            print(f"WARN: capped-read line count={t.count(old_read)}, left as-is", file=sys.stderr)
    P.write_text(t)
    print("backend patched")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
