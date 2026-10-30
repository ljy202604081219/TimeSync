from types import SimpleNamespace as NS
from app.scheduler import solve,verify
from app.timeutil import dt

START='2026-11-02T08:00:00+08:00'
END='2026-11-02T18:00:00+08:00'
def task(id=1,duration=60,deadline=END,deps=None):
    return NS(id=id,title=f'T{id}',duration_minutes=duration,deadline=deadline,priority=2,dependencies=deps or [])
def run(tasks,busy=(),previous=None,available=None):
    return solve(tasks,START,END,available or [(dt(START),dt(END))],busy,previous)

def test_normal():
    result=run([task(),task(2)])
    assert result['status']=='optimal'
    verify([task(),task(2)],result['schedule'],START,END,[(dt(START),dt(END))],[])

def test_deadline_impossible():
    assert run([task(duration=90,deadline='2026-11-02T09:00:00+08:00')])['status']=='infeasible'

def test_fixed_course():
    busy=[(dt(START),dt('2026-11-02T12:00:00+08:00'))]
    result=run([task()],busy)
    assert dt(result['schedule'][0]['start'])>=busy[0][1]

def test_dependency():
    result=run([task(),task(2,deps=[1])])
    by={r['task_id']:r for r in result['schedule']}
    assert dt(by[1]['end'])<=dt(by[2]['start'])

def test_cycle_infeasible():
    assert run([task(deps=[2]),task(2,deps=[1])])['status']=='infeasible'

def test_minimal_repair_and_hard_constraints():
    tasks=[task(),task(2),task(3)]
    before=[{'task_id':i,'title':f'T{i}','start':f'2026-11-02T{h:02}:00:00+08:00','end':f'2026-11-02T{h+1:02}:00:00+08:00'} for i,h in [(1,8),(2,10),(3,12)]]
    old={r['task_id']:r for r in before}
    chosen=before[0]
    busy=[(dt(chosen['start']),dt(chosen['end']))]
    repaired=run(tasks,busy,old)
    assert repaired['status']=='optimal'
    verify(tasks,repaired['schedule'],START,END,[(dt(START),dt(END))],busy)
    assert repaired['objectives'][0]['value']==1
    kept=run(tasks,previous=old)
    assert kept['objectives'][0]['value']==0

def test_round_availability_inward():
    available=[(dt('2026-11-02T08:01:00+08:00'),dt('2026-11-02T09:14:00+08:00'))]
    assert run([task()],available=available)['status']=='infeasible'


def test_capacity_diagnostic_respects_deadline_and_busy_time():
    tasks=[task(i,duration=120,deadline='2026-11-02T12:00:00+08:00') for i in (1,2)]
    result=run(tasks,busy=[(dt(START),dt('2026-11-02T09:00:00+08:00'))])
    assert result['status']=='infeasible' and result['schedule']==[]
    assert result['conflicts']==[{'code':'deadline_capacity','task_ids':[1,2],'required_minutes':240,'available_minutes':180}]
    assert '240' in result['diagnostics'][0] and '180' in result['diagnostics'][0]


def test_dependency_chain_diagnostic_and_duplicate_guard():
    result=run([task(duration=120),task(2,duration=60,deadline='2026-11-02T10:00:00+08:00',deps=[1])])
    assert result['conflicts'][0]['code']=='dependency_deadline'
    assert run([task(deps=[2]),task(2,deps=[1])])['conflicts'][0]['code']=='dependency_cycle'
    assert run([task(deps=[9])])['conflicts'][0]['code']=='missing_dependency'
    assert run([task(),task()])['status']=='invalid'


def test_solver_time_budget_does_not_claim_infeasible():
    result=solve([task()],START,END,[(dt(START),dt(END))],time_limit=0)
    assert result['status']=='unknown' and result['schedule']==[]
    assert result['conflicts'][0]['code']=='solver_timeout'


def test_priority_never_overrides_minimal_change_goal():
    low,high=task(),task(2)
    low.priority,high.priority=1,3
    previous={1:{'start':START},2:{'start':'2026-11-02T12:00:00+08:00'}}
    result=run([low,high],previous=previous)
    assert result['status']=='optimal' and result['objectives'][0]['value']==0
    assert {r['task_id']:r['start'] for r in result['schedule']}=={k:v['start'] for k,v in previous.items()}


def test_later_timeout_preserves_already_verified_solution(monkeypatch):
    clock=iter([0,0,4])
    monkeypatch.setattr('app.scheduler.monotonic',lambda:next(clock))
    result=run([task()])
    assert result['status']=='feasible' and len(result['objectives'])==1
    verify([task()],result['schedule'],START,END,[(dt(START),dt(END))],[])


def test_small_schedules_match_independent_exhaustive_search():
    """Guard the new infeasibility prechecks against rejecting a feasible plan."""
    from datetime import timedelta
    from itertools import product
    from random import Random
    rng=Random(41)
    start=dt(START)
    end=start+timedelta(hours=2)
    for _ in range(40):
        blocked={rng.randrange(8) for _ in range(rng.randrange(4))}
        tasks=[task(i,duration=15*rng.randint(1,3),deadline=(start+timedelta(minutes=15*rng.randint(3,8))).isoformat(),deps=[i-1] if i>1 and rng.choice([True,False]) else []) for i in (1,2,3)]
        possible=False
        for starts in product(range(8),repeat=3):
            occupied=set(blocked)
            valid=True
            for i,t in enumerate(tasks):
                duration=t.duration_minutes//15
                slots=set(range(starts[i],starts[i]+duration))
                if starts[i]+duration>8 or start+timedelta(minutes=15*(starts[i]+duration))>dt(t.deadline) or occupied & slots:
                    valid=False;break
                if any(starts[d-1]+tasks[d-1].duration_minutes//15>starts[i] for d in t.dependencies):
                    valid=False;break
                occupied.update(slots)
            if valid:
                possible=True;break
        busy=[(start+timedelta(minutes=15*i),start+timedelta(minutes=15*(i+1))) for i in blocked]
        result=solve(tasks,start,end,[(start,end)],busy)
        assert (result['status'] in ('optimal','feasible'))==possible,result
        if possible: verify(tasks,result['schedule'],start,end,[(start,end)],busy)
