#!/usr/bin/env python3
"""Bank-consistent OpenSWE routing for the EP8 benchmark (2026-11-03 evening; test code only, no compiled
sources touched). Installs backend/tests/bank_routing.py and the bank subset bank_v4flash_openswe_ep8.npz
into a snapshot and teaches ep_benchmark.py the routing names bank_f<forward>_l<layer>_<placement>:
exact per-expert counts of a real 4K unit per rank, distinct experts per token, placement as a permutation
of expert ids (vanilla / greedy r=0 fitted on forwards 0-255 / random), -1 slots with weight 0 where a unit
routes fewer than six experts for some tokens. Per case the traffic statistics (rows per destination rank,
NIC rows per source, per rail pair the larger direction) are gathered over the ranks and recorded.
"""
import shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1'))
from package import replace  # noqa: E402


def prepare(snapshot):
    out = Path(snapshot); tests = out / 'backend/tests'
    shutil.copy2(HERE / 'bank_routing.py', tests / 'bank_routing.py')
    shutil.copy2(HERE / 'bank_v4flash_openswe_ep8.npz', tests / 'bank_v4flash_openswe_ep8.npz')
    f = tests / 'ep_benchmark.py'
    replace(f, 'from routing import routes, ROUTING_CHOICES\n', 'from routing import routes, ROUTING_CHOICES\nimport bank_routing\n')
    replace(f, '''    else:
        locality=routing if routing in ('local','remote') else 'mixed'
''', '''    elif routing.startswith('bank_'):
        # Bank-consistent routing: exact per-expert counts of a real OpenSWE 4K unit (this rank's unit of
        # the forward), distinct experts per token, placement applied as a permutation of expert ids.
        bank_f,bank_l,bank_placement=bank_routing.parse_bank_name(routing); bank=bank_routing.load_bank(Path(__file__).parent)
        assert n==4096 and (e,k)==(256,6), 'bank routing is defined for 4096-token units of V4 Flash (256 experts, top-6)'
        bank_fi=list(bank['test_forwards']).index(bank_f); bank_counts=bank['test_counts'][bank_fi,bank_l,rank].astype(np.int64)
        bank_perm={'vanilla':np.arange(e),'greedy':bank['greedy_perm'][bank_l],'random':bank['random_perm']}[bank_placement]
        bank_ids=np.append(bank_perm,-1)[bank_routing.bank_routes(bank_counts,n,k,seed*1000+rank)]
        idx=torch.tensor(bank_ids,dtype=torch.int64,device='cuda')
    else:
        locality=routing if routing in ('local','remote') else 'mixed'
''')
    replace(f, "    w=torch.rand(n,k,device='cuda'); w=w/w.sum(1,keepdim=True)\n",
            "    w=torch.rand(n,k,device='cuda'); w=torch.where(idx<0,torch.zeros_like(w),w); w=w/w.sum(1,keepdim=True)\n")
    replace(f, "    diagnostic_watch.mark('case_start', model=model, tokens=n, dtype=dtype, routing=routing, seed=seed, operation=None)\n",
            '''    if routing.startswith('bank_'):
        rows=bank_routing.route_matrix(bank_ids,ep).tolist(); nic=bank_routing.nic_rows(bank_ids,ep,rank)
        gathered=[None]*ep; dist.all_gather_object(gathered,(rows,nic))
        case['bank']=dict(forward=bank_f,layer=bank_l,placement=bank_placement,unit=8*bank_f+rank,
            tokens_with_fewer_experts=int((idx<0).any(1).sum().item()),
            **bank_routing.traffic_stats([g[0] for g in gathered],[g[1] for g in gathered]))
    diagnostic_watch.mark('case_start', model=model, tokens=n, dtype=dtype, routing=routing, seed=seed, operation=None)
''')
    replace(f, "    p.add_argument('--routing',nargs='+',choices=ROUTING_CHOICES,default=['uniform','mixed'])\n",
            "    p.add_argument('--routing',nargs='+',type=bank_routing.routing_name,default=['uniform','mixed'])\n")
    # routing_name validator and the bank loader live in bank_routing (shared with the local builder).
    r = tests / 'bank_routing.py'
    r.write_text(r.read_text() + '''

_BANK = {}


def load_bank(directory):
    """The bank subset shipped next to the benchmark (cached)."""
    if 'bank' not in _BANK:
        z = np.load(str(directory / 'bank_v4flash_openswe_ep8.npz'), allow_pickle=True)
        _BANK['bank'] = {k: z[k] for k in z.files}
    return _BANK['bank']


def routing_name(name):
    from routing import ROUTING_CHOICES
    if name in ROUTING_CHOICES or parse_bank_name(name):
        return name
    raise ValueError('unknown routing ' + name)
''')
    return out


if __name__ == '__main__':
    prepare(sys.argv[1]); print('prepared', sys.argv[1])
