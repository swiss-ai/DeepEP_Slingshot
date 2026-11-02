"""Analyze qualified transport interventions using local clocks and rank-max timers."""
import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('job',type=Path);p.add_argument('--warmup',type=int,default=5)
    p.add_argument('--snapshot',default='source-ladder-v2')
    p.add_argument('--output',default='ladder-analysis')
    p.add_argument('--expected',type=int,default=20)
    args=p.parse_args();out=args.job/args.output;out.mkdir(exist_ok=True)
    results=[];detail=[];excluded=[]
    for finished in sorted((args.job/'results/results').glob('*/FINISHED.json')):
        record=json.loads(finished.read_text())
        if Path(record['spec']['snapshot']).name != args.snapshot:continue
        if record['spec']['qualification'] != 'ladder':continue
        if record.get('returncode')!=0 or record.get('qualification',{}).get('status')!='PASS':continue
        env=record['spec']['environment'];tokens=int(env['CXI_LADDER_ROWS'])
        row_bytes=int(env.get('CXI_LADDER_ROW_BYTES','4320'))
        batch_rows=int(env.get('CXI_LADDER_BATCH_ROWS','0'))
        publish_interval=int(env.get('CXI_LADDER_PUBLISH_INTERVAL','0'))
        assert row_bytes in (4320,8256), 'Unsupported probe row width'
        dimensions=list(map(int,env['CXI_LADDER_CONTEXTS'].split(',')))
        # FINISHED can arrive through rsync before the rank files. Admit an
        # entire gate only after every expected local file is complete.
        collected={};rounds=int(env['CXI_LADDER_ROUNDS'])
        try:
            for contexts in dimensions:
                for rank in range(8):
                    path=finished.parent/'direct/smoke'/('contexts%d-rank%d.jsonl'%(contexts,rank))
                    rows=[json.loads(line) for line in path.read_text().splitlines()]
                    timers=[r for r in rows if 'cuda_ms' in r]
                    stamps=[r for r in rows if 'channel' in r]
                    assert rows[-1].get('complete') is True and rows[-1].get('rc')==0
                    assert len(timers)==rounds and {r['iteration'] for r in timers}==set(range(rounds))
                    assert all(r['errors']==0 and r['row_bytes']==row_bytes for r in timers)
                    assert all(r.get('batch_rows',0)==batch_rows and
                               r.get('publish_interval',0)==publish_interval for r in timers)
                    assert len(stamps)==rounds*256 and {(r['iteration'],r['channel']) for r in stamps}=={
                        (i,c) for i in range(rounds) for c in range(256)}
                    assert all(r['rank']==rank and r['errors']==0 and
                               0<r['ready_ns']<=r['submitted_ns']<=r['flushed_ns']<=r['received_ns'] for r in stamps)
                    collected[contexts,rank]=rows
        except (OSError,ValueError,KeyError,IndexError,AssertionError) as error:
            excluded.append(finished.parent.name+': local evidence incomplete or malformed ('+type(error).__name__+')')
            continue
        for contexts in dimensions:
            iterations=defaultdict(list)
            for rank in range(8):
                rows=collected[contexts,rank]
                times={r['iteration']:r for r in rows if 'cuda_ms' in r}
                channels=defaultdict(list)
                for r in rows:
                    if 'channel' in r:channels[r['iteration']].append(r)
                for iteration,timer in times.items():
                    if iteration<args.warmup:continue
                    stamps=channels[iteration];assert len(stamps)==256
                    assert timer['errors']==0 and timer['row_bytes']==row_bytes
                    last=max(stamps,key=lambda r:r['received_ns'])
                    origin=min(r['ready_ns'] for r in stamps)
                    last_submission=max(r['submitted_ns'] for r in stamps)
                    last_flush=max(r['flushed_ns'] for r in stamps)
                    last_receive=max(r['received_ns'] for r in stamps)
                    d=dict(step=finished.parent.name,variant=env['CXI_VARIANT'],contexts=contexts,tokens=tokens,row_bytes=row_bytes,rank=rank,iteration=iteration,
                           cuda_ms=timer['cuda_ms'],
                           local_phase_span_ms=(last_receive-origin)/1e6,
                           readiness_spread_ms=(max(r['ready_ns'] for r in stamps)-origin)/1e6,
                           all_submission_span_ms=(last_submission-origin)/1e6,
                           after_last_submission_ms=(last_receive-last_submission)/1e6,
                           after_last_flush_ms=(last_receive-last_flush)/1e6,
                           critical_channel=last['channel'],
                           critical_submission_ms=(last['submitted_ns']-last['ready_ns'])/1e6,
                           critical_final_completion_ms=(last['flushed_ns']-last['submitted_ns'])/1e6,
                           critical_receive_wait_ms=(last['received_ns']-last['flushed_ns'])/1e6)
                    detail.append(d);iterations[iteration].append(d)
            assert iterations and all({r['rank'] for r in rows}==set(range(8)) for rows in iterations.values())
            samples=[max(r['cuda_ms'] for r in rows) for rows in iterations.values()]
            values=[r for rows in iterations.values() for r in rows]
            median=statistics.median(samples)
            summary=dict(step=finished.parent.name,variant=env['CXI_VARIANT'],tokens=tokens,row_bytes=row_bytes,contexts=contexts,
                         coalesce=bool(int(env['CXI_LADDER_COALESCE'])),signal_interval=int(env['CXI_LADDER_SIGNAL_INTERVAL']),
                         batch_rows=batch_rows,publish_interval=publish_interval,
                         timed_iterations=len(samples),median_rank_max_ms=median,
                         payload_serialization_ms=tokens*row_bytes/25e6,effective_payload_GBps=tokens*row_bytes/median/1e6)
            for key in ['local_phase_span_ms','critical_submission_ms','critical_final_completion_ms','critical_receive_wait_ms',
                        'readiness_spread_ms','all_submission_span_ms','after_last_submission_ms','after_last_flush_ms']:
                summary[key]=statistics.median(r[key] for r in values)
            results.append(summary)
    for name,rows in [('summary.csv',results),('local-channel-times.csv',detail)]:
        if rows:
            with (out/name).open('w') as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        elif (out/name).exists():
            (out/name).unlink()
    lines=['# Public-GIN transport ladder', '',
           'Qualified cases only; first %d iterations excluded. This is a prepacked transport probe, not complete EP.'%args.warmup,'',
           'Snapshot: `'+args.snapshot+'`.', '',
           '| Variant | Tokens/rank | Row bytes | Contexts | Coalesced | Batch limit / signal / publication interval | Rank-max median ms | Effective payload GB/s |',
           '|---|---:|---:|---:|---|---|---:|---:|']
    for r in results:
        lines.append('| %s | %d | %d | %d | %s | %d / %d / %d | %.4f | %.3f |'%(r['variant'],r['tokens'],r['row_bytes'],r['contexts'],r['coalesce'],r['batch_rows'],r['signal_interval'],r['publish_interval'],r['median_rank_max_ms'],r['effective_payload_GBps']))
    lines+=['','CUDA events include the initial GPU readiness exchange and transfer-kernel boundaries. Preparation, host collective and payload verification are outside.',
            'Batch limit0 means all channel rows when coalescing is enabled, otherwise one row per PUT. Signal interval0 means only the final strong signal; publication interval0 leaves payload PUTs aggregated. Nonzero intervals split PUTs at every requested boundary.',
            'Per-channel submission includes periodic signal/completion work. Final completion includes the final readiness signal and flush. These are GPU-observed software intervals, not wire timestamps.',
            'Local channel intervals overlap. The CSV selects each rank’s latest-finishing channel; do not sum these medians into the overall latency. No cross-node clock equality is assumed.',
            'Cases present: %d/%d. Missing or failed cases are not evidence of success.'%(len(results),args.expected)]
    lines+=['','## All-channel local boundaries','',
            'Medians over each rank/iteration, normalized to that rank’s first ready channel. '
            'Readiness spread is latest-ready minus first-ready. Submission span ends when every producer has returned '
            'from its payload-PUT/periodic-signal loop. AggregateRequests may still defer publication. '
            'The remaining tail includes final signal publication, flush/completion and peer readiness; it is not isolated network time. '
            'Intervals from different channels overlap; medians of adjacent spans need not add to a median total. '
            'These are local envelopes, not a clock-aligned cross-rank trace.','',
            '| Step | Ready spread ms | All-submission span ms | Tail after last submission ms | Tail after last flush ms |',
            '|---|---:|---:|---:|---:|']
    for r in results:
        lines.append('| %s / q%d | %.4f | %.4f | %.4f | %.4f |'%(
            r['step'],r['contexts'],r['readiness_spread_ms'],
            r['all_submission_span_ms'],r['after_last_submission_ms'],r['after_last_flush_ms']))
    if excluded:lines+=['','Excluded from this collection:','']+['- '+item for item in excluded]
    (out/'summary.md').write_text('\n'.join(lines)+'\n');print(out/'summary.md')


if __name__=='__main__':main()
