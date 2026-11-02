#!/usr/bin/env python3
"""Collect and tabulate one cxi_write_bw job (tools/cxi_gin/experiments/link_rate_1102/run.sbatch).

usage: collect_write_bw.py JOBID [--fetch]

--fetch rsyncs /iopsstor/scratch/cscs/zyu/cxi-write-bw-20261102/job-JOBID from clariden into
results/cxi_write_bw_20261102/job-JOBID. Then every *.client.txt is parsed: the configuration
lines the tool prints (memory placement, bidirectional flag, list size, buffer alignment) and the
result rows "RDMA Size[B]  Writes  BW[MB/s]  PktRate[Mpkt/s]". BW is the client's own write rate,
MB = 1e6 bytes as printed by the tool. Nothing is interpolated; failed runs are listed with their
first error line.
"""
import argparse, re, subprocess, sys
from pathlib import Path
ap = argparse.ArgumentParser(); ap.add_argument('job'); ap.add_argument('--fetch', action='store_true'); a = ap.parse_args()
ROOT = Path(__file__).resolve().parents[4]; local = ROOT / 'results/cxi_write_bw_20261102' / ('job-' + a.job)
if a.fetch:
    local.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['rsync', '-a', 'clariden:/iopsstor/scratch/cscs/zyu/cxi-write-bw-20261102/job-%s/' % a.job, str(local) + '/'], check=True)
    subprocess.run(['rsync', '-a', 'clariden:/iopsstor/scratch/cscs/zyu/cxi-write-bw-20261102/job-%s.log' % a.job, str(local / 'slurm.log')], check=False)
row_re = re.compile(r'^\s*(\d+)\s+(\d+)\s+([0-9.]+)\s+([0-9.]+)\s*$')
rows, failed = [], []
for f in sorted(local.glob('*.client.txt')):
    text = f.read_text(); name = f.name[:-len('.client.txt')]
    cfg = {k.strip(): v.strip() for k, v in re.findall(r'^([A-Za-z ()0-9]+?)\s*:\s*(.*)$', text, re.M)}
    res = [row_re.match(l) for l in text.splitlines()]; res = [m for m in res if m]
    rc = re.search(r'# rc=(\d+)', text); rc = int(rc.group(1)) if rc else None
    if not res:
        err = next((l for l in text.splitlines() if re.search(r'error|errx|fail|unable|denied|Invalid', l, re.I)), '')
        failed.append((name, rc, err[:120])); continue
    for m in res:
        size, writes, mbps, pkt = int(m[1]), int(m[2]), float(m[3]), float(m[4])
        rows.append(dict(test=name, size=size, writes=writes, gbps=mbps / 1e3, pkt_mps=pkt, rc=rc,
                         tx=cfg.get('Client TX Mem', 'host'), rx=cfg.get('Server RX Mem', 'host'),
                         bidir=cfg.get('Bidirectional', '?'), list_size=cfg.get('List Size', '?'), align=cfg.get('RDMA Buf Align', '?')))
print('| test | size B | client TX mem | server RX mem | bidir | list | align | writes | GB/s (1e9 B/s) | Mpkt/s |')
print('|---|---:|---|---|---|---:|---:|---:|---:|---:|')
for r in rows:
    print('| %(test)s | %(size)d | %(tx)s | %(rx)s | %(bidir)s | %(list_size)s | %(align)s | %(writes)d | %(gbps).2f | %(pkt_mps).3f |' % r)
if failed:
    print('\nfailed or no result rows:')
    for n, rc, e in failed: print('  %s rc=%s %s' % (n, rc, e))
print('\n%d result rows from %d client files' % (len(rows), len(list(local.glob('*.client.txt')))))
