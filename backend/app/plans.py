import hashlib
import json
from sqlalchemy import select
from .models import Task,BusyInterval,Availability,Meeting,MeetingInvitation,PlanVersion,ScheduledTask,User
from .timeutil import dt,expand,now
from .scheduler import solve,verify

def rows(db, cls, owner):
    # Stable ordering: PostgreSQL does not guarantee insertion order, and the
    # snapshot hash / change list / agenda revision must not depend on it.
    return list(db.scalars(select(cls).where(cls.owner_id==owner).order_by(cls.id)))

def latest(db,owner):
    return db.scalar(select(PlanVersion).where(PlanVersion.owner_id==owner,PlanVersion.status.in_(['optimal','feasible'])).order_by(PlanVersion.id.desc()))

def schedule_rows(db,plan):
    if not plan: return []
    items=db.scalars(select(ScheduledTask).where(ScheduledTask.plan_id==plan.id).order_by(ScheduledTask.start,ScheduledTask.id))
    return [{'task_id':r.task_id,'title':db.get(Task,r.task_id).title,'start':r.start,'end':r.end} for r in items]

def constraints(db,user,extra=(),ignore_meeting=None):
    available=expand([r for r in rows(db,Availability,user.id) if r.kind=='available'],user.window_start,user.window_end)
    busy=expand(rows(db,BusyInterval,user.id),user.window_start,user.window_end)
    meetings=list(db.scalars(select(Meeting).join(MeetingInvitation).where(MeetingInvitation.member_id==user.id,Meeting.status=='confirmed')))
    busy += [(dt(m.start),dt(m.end)) for m in meetings if m.id!=ignore_meeting]
    return available,busy+list(extra)

def snapshot(db,user):
    data={'tasks':[serialize(t) for t in rows(db,Task,user.id)],'busy':[serialize(t) for t in rows(db,BusyInterval,user.id)],'availability':[serialize(t) for t in rows(db,Availability,user.id)],'window':[user.window_start,user.window_end],'meetings':[serialize(t) for t in db.scalars(select(Meeting).join(MeetingInvitation).where(MeetingInvitation.member_id==user.id,Meeting.status=='confirmed'))]}
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()

def serialize(row):
    return {c.name:getattr(row,c.name) for c in row.__table__.columns}

def compute(db,user,extra=(),ignore_meeting=None,placements=None):
    old=latest(db,user.id)
    before=schedule_rows(db,old)
    available,busy=constraints(db,user,extra,ignore_meeting)
    result=solve(rows(db,Task,user.id),user.window_start,user.window_end,available,busy,{r['task_id']:r for r in before},placements=placements)
    if not available and result['status']=='infeasible' and all(c['code']=='no_contiguous_slot' for c in result.get('conflicts',[])):
        configured=any(r.kind=='available' for r in rows(db,Availability,user.id))
        result['availability_status']='outside_window' if configured else 'missing'
        result['diagnostics']=[('已设置的可用时段没有覆盖当前规划窗口。' if configured else '尚未设置可排程时段，这不代表日历里没有空闲。')+'请选择允许排程的时段后重试。']
    old_by={r['task_id']:r for r in before}
    changes=[]
    for row in result['schedule']:
        prev=old_by.get(row['task_id'])
        if not prev or prev['start']!=row['start'] or prev['end']!=row['end']:
            reason='新增约束或依赖使原时间不可用；按最少改动目标重新安排。' if prev else '新增任务首次安排。'
            if placements:
                reason='按你指定的时段调整，并验证课程、DDL和任务依赖。' if row['task_id'] in placements else '为配合指定任务时段，按最少改动目标调整。'
            changes.append({'task_id':row['task_id'],'title':row['title'],'before':prev,'after':row,'reason':reason})
    return {**result,'before':before,'changes':changes,'expected_plan_id':old.id if old else None,'expected_snapshot':snapshot(db,user)}

def persist(db,user,result,reason):
    plan=PlanVersion(owner_id=user.id,parent_id=result['expected_plan_id'],reason=reason,created_at=now(),status=result['status'],changes=result['changes'],diagnostics=result['diagnostics'])
    db.add(plan);db.flush()
    for row in result['schedule']:
        db.add(ScheduledTask(plan_id=plan.id,task_id=row['task_id'],start=row['start'],end=row['end']))
    return {**result,'id':plan.id,'reason':reason}

def valid_current(db,user):
    plan=latest(db,user.id)
    if not plan: return False
    a,b=constraints(db,user)
    try:
        verify(rows(db,Task,user.id),schedule_rows(db,plan),dt(user.window_start),dt(user.window_end),a,b)
        return True
    except (AssertionError,KeyError): return False
