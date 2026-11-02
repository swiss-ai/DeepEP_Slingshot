"""Localize SGLang smoke journals/JIT; apply only to a new immutable snapshot."""
from pathlib import Path
from package import replace


def prepare(snapshot):
    script = Path(snapshot)/'backend/tools/direct_node.sh'
    anchor = '  test_args=("$src/tests/sglang_dispatcher_smoke.py")'
    replace(script, anchor, '''  if [ "${CXI_LOCAL_JIT:-0}" = 1 ]; then
    export SGLANG_DG_CACHE_DIR="$EP_JIT_CACHE_DIR/sglang-deepgemm"
  fi
  if [ "${CXI_LOCAL_RESULTS:-0}" = 1 ]; then
    sglang_shared_results="$CASE_OUT"
    export CASE_OUT=$(mktemp -d "/dev/shm/deepep-sglang-${SLURM_JOB_ID}-n${SLURM_PROCID}-XXXXXX")
    printf '%s\\n' "$CASE_OUT" > "$base/local-sglang-results-path.txt"
  fi
''' + anchor)
    anchor = 'if [ "$test_rc" != 0 ]; then exit "$test_rc"; fi'
    replace(script, anchor, '''if [ -n "${sglang_shared_results:-}" ]; then
  # Persist only after torchrun exits. Failed tests retain their error records;
  # failed persistence leaves the complete local directory available to debug.
  mkdir -p "$sglang_shared_results"
  cp -r --no-preserve=all "$CASE_OUT/." "$sglang_shared_results/"
  rm -rf -- "$CASE_OUT"
fi
''' + anchor)
    test = Path(snapshot)/'backend/tests/sglang_dispatcher_smoke.py'
    replace(test, "          'gin_type': os.getenv('NCCL_GIN_TYPE'), 'plugin': os.getenv('NCCL_GIN_PLUGIN')}",
        """          'gin_type': os.getenv('NCCL_GIN_TYPE'), 'plugin': os.getenv('NCCL_GIN_PLUGIN'),
          'local_results': os.getenv('CXI_LOCAL_RESULTS') == '1',
          'local_jit': os.getenv('CXI_LOCAL_JIT') == '1',
          'case_out': str(out), 'deepgemm_cache': os.getenv('SGLANG_DG_CACHE_DIR')}""")
    replace(test, "                handle = dispatcher._normal_dispatcher.handle", """                adapter = dispatcher._normal_dispatcher
                actual_ep_config = dict(sms=adapter._sms, allocated_contexts=adapter._contexts,
                    used_qps=adapter._qps, capacity=adapter._capacity,
                    physical_domain=list(adapter._elastic.get_physical_domain_size()))
                handle = adapter.handle""")
    replace(test, "                    source_token_stride=source_stride,", """                    source_token_stride=source_stride,
                    actual_ep_config=actual_ep_config,""")
    validator = Path(snapshot)/'runner/validate_gate.py'
    replace(validator, "    if mode == 'sglang':", """    if mode == 'sglang':
        reports = list((Path(destination)/'compiler-reports').rglob('*.txt'))
        require(bool(reports), 'SGLang actual DeepEP compiler reports missing')
        for key, macro in [('CXI_EP_PACK_ROWS','CXI_EP_PACK_ROWS'),
                           ('CXI_EP_UPDATE_INTERVAL','CXI_EP_UPDATE_INTERVAL')]:
            if key in env:
                require(all('-D'+macro+'='+env[key]+' ' in p.read_text() for p in reports),
                        'SGLang compiler setting missing/mismatched: '+key)""")
    replace(validator, "            require(all(0 <= r['max_abs_error'] < float('inf') for r in cases), 'SGLang nonfinite error')", """            require(all(0 <= r['max_abs_error'] < float('inf') for r in cases), 'SGLang nonfinite error')
            require(all(r.get('actual_ep_config', {}).get('sms') == int(env['CXI_EP_SMS'])
                        and r['actual_ep_config'].get('allocated_contexts') == int(env['CXI_EP_CONTEXTS'])
                        and r['actual_ep_config'].get('used_qps') == int(env['CXI_EP_CONTEXTS'])
                        and r['actual_ep_config'].get('physical_domain') == [2,4]
                        and r['actual_ep_config'].get('capacity') == r['source_token_stride']
                        and r['actual_ep_config']['capacity'] >= r['tokens'] for r in cases),
                    'SGLang actual topology/SM/context/capacity evidence mismatch')""")
