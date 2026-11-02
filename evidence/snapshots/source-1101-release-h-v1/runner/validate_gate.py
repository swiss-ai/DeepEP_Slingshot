#!/usr/bin/env python3
"""Fail-closed evidence gates for one bounded, explicitly scheduled allocation.

Compatible with the login node's Python 3.6. This validates prepared tests; it
does not invent fixes, submit jobs, or treat a zero batch exit as correctness.
"""
import json
import re
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def json_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def qualify(destination, spec):
    mode = spec['qualification']
    env = spec.get('environment', {})
    transport = env.get('CXI_TRANSPORT', 'direct')
    if mode == 'dynamic':
        require(transport == 'direct', 'raw CXI qualification requires direct transport')
        for node in range(2):
            base = Path(destination) / 'dynamic' / ('node%d' % node)
            statuses = [line.split() for line in (base / 'status.tsv').read_text().splitlines() if line.strip()]
            require(len(statuses) == 4 and sorted(statuses) == [[str(gpu), '0'] for gpu in range(4)],
                    'raw probe GPU processes did not all exit successfully')
            for gpu in range(4):
                rows = [json.loads(line) for line in (base / ('gpu%d.log' % gpu)).read_text().splitlines()
                        if line.startswith('{')]
                rank = node * 4 + gpu
                require(len(rows) == 2 and all(row.get('rank') == rank for row in rows),
                        'raw probe missing or unexpected rank evidence')
                payload, teardown = rows
                require(payload.get('stage') == 'dynamic_result' and payload.get('cases') == 18
                        and payload.get('errors') == 0 and payload.get('diagnostic') == 0
                        and payload.get('posted') == payload.get('completed') == 100,
                        'raw dynamic payload/completion failure')
                require(teardown.get('stage') == 'process_result' and teardown.get('rc') == 0
                        and teardown.get('is_nccl_gin') is False, 'raw probe cleanup or scope failure')
        return {'status': 'PASS', 'kind': 'raw_dynamic', 'ranks': 8, 'cases_per_rank': 18,
                'scope': 'raw CXI primitives only; not public GIN or DeepEP'}
    base = Path(destination) / transport
    require(all((base / ('node%d' % node) / 'PASS').is_file() for node in range(2)),
            'both node scripts must finish successfully')
    if mode == 'gin':
        require(transport == 'direct', 'GIN qualification requires direct transport')
        expected_kind = env.get('CXI_TEST_KIND', 'smoke')
        require(expected_kind in ('smoke', 'bounds', 'producer'), 'unqualified GIN gate kind')
        dimensions = [int(v) for v in env.get('CXI_SMOKE_CONTEXTS', '1,4').split(',')]
        if expected_kind == 'bounds':
            dimensions = [1]
        rounds = int(env.get('CXI_SMOKE_ROUNDS', '14'))
        if expected_kind == 'producer':
            dimensions = [int(v) for v in env.get('CXI_PRODUCER_BLOCKS', '1,2,8').split(',')]
            rounds = int(env.get('CXI_PRODUCER_ROUNDS', '128'))
        for rank in range(8):
            record = json.loads((base / 'smoke' / ('rank%d.json' % rank)).read_text())
            require(record['rank'] == rank and record['stage'] == 'complete', 'incomplete rank')
            require(record['gin_type'] == '6' and record['kind'] == expected_kind, 'wrong backend/test')
            require(len(record['cases']) == len(dimensions), 'missing GIN cycles')
            if env.get('CXI_LIFECYCLE_HOLD_WINDOW') == '1':
                require(record.get('held_window') is True and record.get('held_window_released') is True,
                        'persistent lifecycle window not verified')
                if len(dimensions) >= 20 and len(set(dimensions)) == 1:
                    log = (base / ('node%d' % (rank // 4)) / 'smoke.log').read_text()
                    from analyze_lifecycle import audit_rank
                    audit_rank(log, rank % 4, len(dimensions), dimensions[0], True)
            evidence = set()
            for cycle, case in enumerate(record['cases']):
                require(case['returncode'] == 0 and case['cycle'] == cycle, 'failed or unordered cycle')
                filename = case['evidence']
                require(Path(filename).name == filename and filename not in evidence, 'unsafe/reused evidence')
                evidence.add(filename)
                rows = json_lines(base / 'smoke' / filename)
                require(rows and rows[-1].get('complete') is True and rows[-1].get('rc') == 0,
                        'missing successful teardown')
                require(all(r.get('errors', 0) == 0 and not r.get('exception') for r in rows), 'GPU errors')
                if expected_kind == 'bounds':
                    require(any(r.get('cases') == 5 and r.get('errors') == 0 for r in rows), 'bounds cases missing')
                    continue
                if expected_kind == 'producer':
                    blocks = dimensions[cycle]
                    require(case.get('blocks') == blocks, 'wrong producer CTA count')
                    producers = [r for r in rows if 'block' in r]
                    require(len(producers) == blocks and {r['block'] for r in producers} == set(range(blocks))
                            and all(r.get('rounds') == rounds and r.get('errors') == 0 for r in producers),
                            'missing or failed producer CTA results')
                    require(rows[-1].get('blocks') == blocks and rows[-1].get('rounds_requested') == rounds,
                            'producer teardown dimensions mismatch')
                    continue
                if env.get('CXI_MUTATION_EXPECT'):
                    probes=[r for r in rows if r.get('mutation_probe')]
                    expected=env['CXI_MUTATION_EXPECT']=='clobber'
                    require(len(probes)==1 and probes[0].get('expect_clobber')==expected and
                            probes[0].get('rounds')==100 and probes[0].get('errors')==0 and
                            probes[0].get('observed')==(0xff000000 if expected else 0),
                            'receiver-mutation diagnostic failed')
                contexts = dimensions[cycle]
                require(case.get('contexts') == contexts, 'wrong context count')
                normal = [r for r in rows if 'context' in r and 'rounds' in r and 'reset_epoch' not in r]
                require(len(normal) == contexts and {r['context'] for r in normal} == set(range(contexts)),
                        'missing context results')
                require(all(r['rounds'] == rounds for r in normal), 'missing payload rounds')
                if env.get('CXI_SMOKE_RESET'):
                    reset = [r for r in rows if r.get('reset_epoch') == 1]
                    require(len(reset) == contexts and {r['context'] for r in reset} == set(range(contexts))
                            and all(r['rounds'] == rounds for r in reset), 'missing reset epoch')
                if env.get('CXI_SMOKE_NEGATIVE'):
                    versions = [r for r in rows if r.get('negative_version')]
                    require(len(versions) == 1 and versions[0]['rc'] == versions[0]['expected']
                            and versions[0]['rc'] != 0, 'invalid version was not rejected')
                    delays = [r for r in rows if r.get('delayed_peer')]
                    require(len(delays) == 1 and delays[0]['rank'] == rank
                            and delays[0]['first'] == delays[0]['expected_first']
                            and delays[0]['recovered'] == 0 and delays[0]['flush'] == 0,
                            'timeout recovery did not pass')
                if env.get('CXI_SMOKE_SELF'):
                    signals = [r for r in rows if r.get('self_signal')]
                    require(len(signals) == contexts and {r['context'] for r in signals} == set(range(contexts))
                            and all(r['rc'] == 0 for r in signals), 'self signaling did not pass')
        return {'status': 'PASS', 'kind': expected_kind, 'ranks': 8, 'cycles_per_rank': len(dimensions)}
    if mode == 'ep':
        if env.get('CXI_REQUIRE_REUSE') == '1':
            import re
            for node in range(2):
                text=(base/('node%d'%node)/'smoke.log').read_text()
                entries=re.findall(r'CXI pool phase=context-created gpu=(\d+) created=(\d+) reused=(\d+) allocated=(\d+) idle=(\d+) ct_in_use=(\d+) usage_rc=(\d+)',text)
                for gpu in range(4):
                    rows=[tuple(map(int,x)) for x in entries if int(x[0])==gpu]
                    require(rows and all(x[6]==0 for x in rows), 'missing/error lifecycle resource records')
                    require(max(x[2] for x in rows)>0, 'healthy channels never reused')
                    require(max(x[1] for x in rows)<=260 and max(x[5] for x in rows)<=260,
                            'CT resources did not plateau below the service limit')
                require('CXI_RETIRE_REFRESH ' in text and 'teardown_only=1' in text,
                        'retirement completion refresh was not exercised')

        merged_final=env.get('CXI_EP_MERGE_FINAL_TAIL')
        if merged_final is not None:
            require(merged_final in ('0','1'), 'invalid final-tail mode')
            reports=list((Path(destination)/'compiler-reports').rglob('*.txt'))
            require(reports and all('-DCXI_EP_MERGE_FINAL_TAIL='+merged_final+' ' in p.read_text() for p in reports),
                    'final-tail compiler evidence missing or mismatched')
        packc = env.get('CXI_EP_PACK_COMBINE')
        if packc is not None:
            require(packc in ('0','1'), 'invalid packed-combine mode')
            reports = list((Path(destination)/'compiler-reports').rglob('*.txt'))
            require(reports and all('-DCXI_EP_PACK_COMBINE='+packc+' ' in p.read_text() for p in reports),
                    'packed-combine compiler evidence missing or mismatched')
        packed = env.get('CXI_EP_PACK_ROWS')
        if packed is not None:
            require(packed in ('0','1'), 'invalid packed-row mode')
            reports = list((Path(destination)/'compiler-reports').rglob('*.txt'))
            require(reports and all('-DCXI_EP_PACK_ROWS='+packed+' ' in p.read_text() for p in reports),
                    'packed-row compiler evidence missing or mismatched')
        ep = base / 'ep' 
        if env.get('CXI_DIAGNOSTIC_WATCHDOG') == '1':
            for rank in range(8):
                watch=[json.loads(line) for line in (ep/('diagnostic-watch-rank%d.jsonl'%rank)).read_text().splitlines()]
                require(watch and watch[0]['phase']=='observer_started' and
                        watch[-1]['phase']=='observer_stopped' and watch[-1]['thread_stopped'],
                        'diagnostic observer incomplete')
                require(not any(w.get('diagnostic_code',0) for w in watch), 'GPU diagnostic reported') 
        validation = json.loads((ep / 'validation.json').read_text())
        require(validation['status'] == 'PASS' and validation['ep'] == 8, 'EP summary failed')
        require(not list(ep.glob('failures-rank*.jsonl')), 'EP failure records exist')
        models = env.get('CXI_EP_MODELS', 'v4flash').split()
        tokens = [int(v) for v in env.get('CXI_EP_TOKENS', '32').split()]
        dtypes = env.get('CXI_EP_DTYPES', 'bf16').split()
        routing = env.get('CXI_EP_ROUTING', 'mixed').split()
        seeds = [int(v) for v in env.get('CXI_EP_SEEDS', '1').split()]
        expected = {(m, n, d, r, s) for m in models for n in tokens for d in dtypes for r in routing for s in seeds}
        gin = '6' if transport == 'direct' else '2'
        for rank in range(8):
            require((ep / ('DONE-rank%d' % rank)).is_file(), 'EP rank not done')
            rows = json_lines(ep / ('correctness-rank%d.jsonl' % rank))
            if merged_final is not None:
                require(all(r.get('merged_final_tail') is bool(int(merged_final)) for r in rows),
                        'final-tail rank evidence missing or mismatched')
            if packc is not None:
                require(all(r.get('packed_combine') is bool(int(packc)) for r in rows),
                        'packed-combine rank evidence missing or mismatched')
            if packed is not None:
                require(all(r.get('packed_remote_rows') is bool(int(packed)) for r in rows),
                        'packed-row rank evidence missing or mismatched')
                require(all(r.get('drop_every') == int(env.get('CXI_EP_DROP_EVERY','0')) for r in rows),
                        'dropped-token routing test mismatch')
            keys = {(r['model'], r['tokens_per_gpu'], r['dispatch_dtype'], r['routing'], r['seed']) for r in rows}
            require(len(rows) == len(expected) and keys == expected, 'EP matrix incomplete')
            require(all(r['rank'] == rank and r['ep'] == 8 and r['status'] == 'PASS'
                        and r['gin_type'] == gin for r in rows), 'EP wrong rank/backend or failed correctness')
        return {'status': 'PASS', 'kind': 'ep', 'ranks': 8, 'cases_per_rank': len(expected), 'gin_type': gin}
    if mode == 'sglang':
        reports = list((Path(destination)/'compiler-reports').rglob('*.txt'))
        require(bool(reports), 'SGLang actual DeepEP compiler reports missing')
        for key, macro in [('CXI_EP_PACK_ROWS','CXI_EP_PACK_ROWS'),
                           ('CXI_EP_UPDATE_INTERVAL','CXI_EP_UPDATE_INTERVAL')]:
            if key in env:
                require(all('-D'+macro+'='+env[key]+' ' in p.read_text() for p in reports),
                        'SGLang compiler setting missing/mismatched: '+key)
        require(transport in ('direct', 'proxy'), 'unqualified SGLang transport')
        gin = '6' if transport == 'direct' else '2'
        model = env.get('CXI_SGLANG_MODEL', 'toy')
        dtypes = env.get('CXI_SGLANG_DTYPES', 'bf16,fp8').split(',')
        tokens = [int(n) for n in env.get('CXI_SGLANG_TOKENS', '32,4096').split(',')]
        rounds = int(env.get('CXI_SGLANG_ROUNDS', '3'))
        warmup = int(env.get('CXI_SGLANG_WARMUP', '0'))
        rounds += warmup
        expected = {(d, n, i) for d in dtypes for n in tokens for i in range(rounds)}
        gemm = env.get('CXI_SGLANG_GEMM') == '1'
        permute = env.get('CXI_SGLANG_PERMUTE') == '1' or gemm
        for rank in range(8):
            record = json.loads((base / 'smoke' / ('rank%d.json' % rank)).read_text())
            require(record['rank'] == rank and record['stage'] == 'complete'
                    and record['result'] == 'PASS' and not record.get('error'), 'SGLang rank failed')
            require(record['gin_type'] == gin and record['model_geometry'] == model,
                    'SGLang wrong backend or geometry')
            if transport == 'proxy':
                require(record.get('proxy_control') is True and record.get('transport') == 'proxy_ofi_cxi',
                        'SGLang proxy control must be explicitly identified')
            require(record['actual_sglang_scatter_gather'] == permute
                    and record['actual_sglang_expert_kernels'] == gemm, 'SGLang wrong integration scope')
            if env.get('CXI_SGLANG_IMPORT_AFTER_INIT') == '1':
                require(record.get('import_after_group_init') is True, 'late import not exercised')
            cases = record['cases']
            require(len(cases) == len(expected)
                    and {(r['dtype'], r['tokens'], r['step']) for r in cases} == expected,
                    'SGLang matrix incomplete')
            require(all(r.get('warmup', False) == (r['step'] < warmup) for r in cases),
                    'SGLang warmup labels differ from requested schedule')
            require(all(0 <= r['max_abs_error'] < float('inf') for r in cases), 'SGLang nonfinite error')
            require(all(r.get('actual_ep_config', {}).get('sms') == int(env['CXI_EP_SMS'])
                        and r['actual_ep_config'].get('allocated_contexts') == int(env['CXI_EP_CONTEXTS'])
                        and r['actual_ep_config'].get('used_qps') == int(env['CXI_EP_CONTEXTS'])
                        and r['actual_ep_config'].get('physical_domain') == [2,4]
                        and r['actual_ep_config'].get('capacity') == r['source_token_stride']
                        and r['actual_ep_config']['capacity'] >= r['tokens'] for r in cases),
                    'SGLang actual topology/SM/context/capacity evidence mismatch')
            if env.get('CXI_SGLANG_EXACT_REFERENCE') == '1':
                require(record.get('exact_dispatch_reference') is True and
                        all(r.get('exact_dispatch_reference') == 'PASS' for r in cases),
                        'SGLang exact payload/scale/routing reference missing')
            require((base / 'smoke' / ('libraries-rank%d.txt' % rank)).is_file(), 'SGLang loaded paths missing')
        return {'status': 'PASS', 'kind': 'sglang', 'ranks': 8, 'cases_per_rank': len(expected),
                'model_geometry': model, 'actual_expert_kernels': gemm, 'actual_scatter_gather': permute,
                'transport': transport, 'gin_type': gin}
    raise ValueError('unsupported qualification: ' + mode)
