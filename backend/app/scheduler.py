"""Deterministic CP-SAT scheduling. Hard feasibility always precedes soft goals."""
from datetime import timedelta
from math import ceil, floor
from time import monotonic
from ortools.sat.python import cp_model
from .timeutil import dt
from .intervals import merge, subtract, overlap

SLOT=15

def failure(status,code,message,task_ids=(),**details):
    return {'status':status,'diagnostics':[message],'conflicts':[{'code':code,'task_ids':list(task_ids),**details}],'schedule':[]}


def solve(tasks, start, end, available, busy=(), previous=None, time_limit=3, placements=None):
    start,end=dt(start),dt(end)
    previous=previous or {}
    horizon=floor((end-start).total_seconds()/900)
    if horizon<=0 or horizon>14*96 or len(tasks)>60:
        return failure('invalid','planning_limits','排程窗口需为 15 分钟至 14 天，任务最多 60 项。')
    by_id={t.id:t for t in tasks}
    if len(by_id)!=len(tasks):
        return failure('invalid','duplicate_task','任务 ID 重复，不能重复安排。')
    ordered,visiting,visited=[],[],set()
    def visit(task):
        if task.id in visiting:
            cycle=visiting[visiting.index(task.id):]+[task.id]
            return failure('infeasible','dependency_cycle','前置依赖形成循环：'+' → '.join(by_id[i].title for i in cycle),cycle)
        if task.id in visited: return None
        visiting.append(task.id)
        for dep in task.dependencies:
            if dep not in by_id:
                return failure('invalid','missing_dependency',f'「{task.title}」引用了不存在的前置任务 #{dep}。',[task.id])
            error=visit(by_id[dep])
            if error: return error
        visiting.pop();visited.add(task.id);ordered.append(task)
        return None
    for task in tasks:
        error=visit(task)
        if error: return error
    free=subtract(available,busy)
    model=cp_model.CpModel()
    starts,ends,intervals={},{},[]
    diagnostics,conflicts,domains=[],[],{}
    for task in tasks:
        duration=ceil(task.duration_minutes/SLOT)
        latest=floor((dt(task.deadline)-start).total_seconds()/900)-duration
        ranges=[]
        task_free=free
        if placements and task.id in placements:
            from .intervals import intersect
            task_free=intersect(free,[tuple(map(dt,placements[task.id]))])
        for a,b in task_free:
            lo=max(0,ceil((a-start).total_seconds()/900))
            hi=min(horizon-duration,latest,floor((b-start).total_seconds()/900)-duration)
            if lo<=hi: ranges.append((lo,hi))
        if not ranges:
            diagnostics.append(f'「{task.title}」在截止前没有连续 {task.duration_minutes} 分钟的可用空档。')
            conflicts.append({'code':'no_contiguous_slot','task_ids':[task.id],'required_minutes':task.duration_minutes})
            continue
        domains[task.id]=ranges
        s=model.new_int_var_from_domain(cp_model.Domain.from_intervals(ranges),f's_{task.id}')
        e=model.new_int_var(0,horizon,f'e_{task.id}')
        starts[task.id],ends[task.id]=s,e
        intervals.append(model.new_interval_var(s,duration,e,f't_{task.id}'))
    if diagnostics:
        return {'status':'infeasible','diagnostics':diagnostics,'conflicts':conflicts,'schedule':[]}
    # Necessary bounds only: CP-SAT remains the final feasibility authority.
    earliest_ends={}
    for task in ordered:
        after=max((earliest_ends[d] for d in task.dependencies),default=0)
        earliest=next((max(lo,after) for lo,hi in domains[task.id] if max(lo,after)<=hi),None)
        if earliest is None:
            return failure('infeasible','dependency_deadline',f'「{task.title}」完成所有前置任务后，截止前已没有足够的连续空档。',[*task.dependencies,task.id])
        earliest_ends[task.id]=earliest+ceil(task.duration_minutes/SLOT)
    deadlines={t.id:min(horizon,floor((dt(t.deadline)-start).total_seconds()/900)) for t in tasks}
    for boundary in sorted(set(deadlines.values())):
        due=[t for t in tasks if deadlines[t.id]<=boundary]
        required=sum(ceil(t.duration_minutes/SLOT) for t in due)
        capacity=sum(max(0,min(boundary,floor((b-start).total_seconds()/900))-max(0,ceil((a-start).total_seconds()/900))) for a,b in free)
        if required>capacity:
            until=(start+timedelta(minutes=SLOT*boundary)).strftime('%m-%d %H:%M')
            return failure('infeasible','deadline_capacity',f'{until} 前需完成 {len(due)} 项任务，共 {required*SLOT} 分钟，但扣除固定安排后只有 {capacity*SLOT} 分钟可用。',[t.id for t in due],required_minutes=required*SLOT,available_minutes=capacity*SLOT)
    for task in tasks:
        for dep in task.dependencies:
            model.add(starts[task.id]>=ends[dep])
    model.add_no_overlap(intervals)
    moved,distances=[],[]
    for task in tasks:
        if task.id not in previous: continue
        old=round((dt(previous[task.id]['start'])-start).total_seconds()/900)
        changed=model.new_bool_var(f'moved_{task.id}')
        model.add(starts[task.id]==old).only_enforce_if(changed.negated())
        model.add(starts[task.id]!=old).only_enforce_if(changed)
        distance=model.new_int_var(0,max(horizon,abs(old)+horizon),f'distance_{task.id}')
        model.add_abs_equality(distance,starts[task.id]-old)
        moved.append(changed); distances.append(distance)
    # Penalize 15/30-minute holes between tasks.
    # ponytail: O(n²) soft gap checks, cap at 60 tasks; use a circuit model if needed.
    fragments=[]
    for i,a in enumerate(tasks):
        for b in tasks[i+1:]:
            for left,right in ((a,b),(b,a)):
                near=model.new_bool_var(f'near_{left.id}_{right.id}')
                model.add_linear_expression_in_domain(starts[right.id]-ends[left.id],cp_model.Domain.from_intervals([[1,2]])).only_enforce_if(near)
                model.add_linear_expression_in_domain(starts[right.id]-ends[left.id],cp_model.Domain.from_intervals([[-horizon,0],[3,horizon]])).only_enforce_if(near.negated())
                fragments.append(near)
    objectives=[sum(moved),sum(distances),sum(fragments),sum(t.priority*starts[t.id] for t in tasks)]
    solver=cp_model.CpSolver()
    solver.parameters.num_search_workers=1
    solver.parameters.random_seed=7
    stages=[]
    best=None
    expires=monotonic()+max(0,time_limit)
    for label,objective in zip(['changed_tasks','movement_slots','fragmentation','priority'],objectives):
        remaining=expires-monotonic()
        if remaining<=0:
            if best is not None: break
            return failure('unknown','solver_timeout','求解时间预算已用尽，尚未找到可行解；没有生成计划。')
        solver.parameters.max_time_in_seconds=remaining
        model.minimize(objective)
        status=solver.solve(model)
        if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
            if best is not None: break
            reason='约束组合不可行：检查总耗时、DDL、任务依赖及固定时段。' if status==cp_model.INFEASIBLE else '求解超时，尚未找到可行解；没有生成计划。'
            return failure('infeasible' if status==cp_model.INFEASIBLE else 'unknown','combined_constraints' if status==cp_model.INFEASIBLE else 'solver_timeout',reason,[t.id for t in tasks])
        best=[{'task_id':t.id,'title':t.title,'start':(start+timedelta(minutes=SLOT*solver.value(starts[t.id]))).isoformat(),'end':(start+timedelta(minutes=SLOT*solver.value(ends[t.id]))).isoformat()} for t in tasks]
        value=round(solver.objective_value)
        stages.append({'goal':label,'value':value,'optimal':status==cp_model.OPTIMAL})
        if status!=cp_model.OPTIMAL: break  # Never degrade an unproven higher-priority objective.
        model.add(objective==value)
    verify(tasks,best or [],start,end,available,busy,placements)
    return {'status':'optimal' if len(stages)==4 and all(s['optimal'] for s in stages) else 'feasible','schedule':best or [],'diagnostics':[],'conflicts':[],'objectives':stages}

def verify(tasks,schedule,start,end,available,busy,placements=None):
    """Independent post-solve guard; a bad schedule is never persisted."""
    assert len(schedule)==len(tasks)
    by_id={r['task_id']:r for r in schedule}
    assert len(by_id)==len(tasks)
    free=subtract(available,busy)
    for task in tasks:
        row=by_id[task.id]; a,b=dt(row['start']),dt(row['end'])
        assert dt(start)<=a<b<=min(dt(end),dt(task.deadline))
        assert (b-a).total_seconds()==ceil(task.duration_minutes/15)*900
        assert any(c<=a and b<=d for c,d in free)
        if placements and task.id in placements:
            lo,hi=map(dt,placements[task.id])
            assert lo<=a<b<=hi
        assert all(dt(by_id[dep]['end'])<=a for dep in task.dependencies)
    for i,row in enumerate(schedule):
        assert all(not overlap(dt(row['start']),dt(row['end']),dt(other['start']),dt(other['end'])) for other in schedule[i+1:])
