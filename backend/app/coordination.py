from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from .models import User,Availability,BusyInterval,Meeting,MeetingInvitation
from .timeutil import dt,expand
from .intervals import subtract,intersect,overlap,candidates,ceil_slot
from .plans import rows,compute,persist,serialize,latest,schedule_rows

def member_free(db,member,start,end,ignore_meeting=None):
    user=db.get(User,member)
    if not user: raise HTTPException(422,'未知成员')
    available=expand([r for r in rows(db,Availability,member) if r.kind=='available'],start,end)
    busy=expand(rows(db,BusyInterval,member),start,end)
    meetings=db.scalars(select(Meeting).join(MeetingInvitation).where(MeetingInvitation.member_id==member,Meeting.status=='confirmed'))
    busy += [(dt(m.start),dt(m.end)) for m in meetings if m.id!=ignore_meeting]
    uncomfortable=expand([r for r in rows(db,Availability,member) if r.kind=='uncomfortable'],start,end)
    return subtract(available,busy),busy,uncomfortable

def find_candidates(db,data,ignore_meeting=None):
    free,busy,uncomfortable={},{},{}
    for member in data.members:
        free[member],busy[member],uncomfortable[member]=member_free(db,member,data.start,data.end,ignore_meeting)
    ranked=candidates(free,data.duration_minutes,uncomfortable,dt(data.preferred) if data.preferred else None)
    alternatives=[]
    if not ranked:
        a=ceil_slot(dt(data.start))
        duration=timedelta(minutes=data.duration_minutes)
        while a+duration<=dt(data.end):
            missing=[member for member in data.members if not any(c<=a and a+duration<=d for c,d in free[member])]
            if len(missing)<len(data.members):
                alternatives.append({'start':a.isoformat(),'end':(a+duration).isoformat(),'available_count':len(data.members)-len(missing),'unavailable_members':missing,'requires_negotiation':True})
            a+=timedelta(minutes=15)
        alternatives.sort(key=lambda r:(-r['available_count'],r['start']))
    return {'candidates':ranked[:40],'total':len(ranked),'alternatives':alternatives[:8],
            'diagnostics':[] if ranked else ['此范围内没有所有必要成员共同可用的连续时段。备选时段需要成员调整安排，不能直接确认为会议。'],
            'members':{m:{'free':[{'start':a.isoformat(),'end':b.isoformat()} for a,b in free[m]],'busy':[{'start':a.isoformat(),'end':b.isoformat()} for a,b in busy[m]]} for m in data.members}}

def invitations(db,meeting):
    return list(db.scalars(select(MeetingInvitation).where(MeetingInvitation.meeting_id==meeting.id)))

def public_meeting(db,meeting,user):
    invites=invitations(db,meeting)
    if user.id not in [i.member_id for i in invites]: raise HTTPException(403,'你不是该会议成员')
    return {**serialize(meeting),'invitations':[{'member_id':i.member_id,'status':i.status} for i in invites]}

def ensure_free(db,members,start,end,ignore=None):
    for member in members:
        free,_,_=member_free(db,member,start,end,ignore)
        if not any(a<=dt(start) and dt(end)<=b for a,b in free):
            raise HTTPException(409,f'成员 {member} 的固定日程或可用时间与会议冲突，请重新计算候选时间')

def create_meeting(db,user,data):
    members=sorted(set(data.members))
    if user.id not in members: raise HTTPException(422,'发起人必须作为必要成员参加')
    if (dt(data.end)-dt(data.start)).total_seconds()%900: raise HTTPException(422,'会议时长须为15分钟的倍数')
    if data.replaces_id:
        old=db.get(Meeting,data.replaces_id)
        if not old: raise HTTPException(404,'原会议不存在')
        if old.organizer_id!=user.id: raise HTTPException(403,'只有发起人可以提出改期')
        if old.status!='confirmed': raise HTTPException(409,'只能为已确认会议提出改期')
        if members!=sorted(i.member_id for i in invitations(db,old)): raise HTTPException(422,'改期必须保留所有原必要成员')
    ensure_free(db,members,data.start,data.end,data.replaces_id)
    meeting=Meeting(organizer_id=user.id,title=data.title,start=data.start,end=data.end,status='pending',replaces_id=data.replaces_id,linkage=[])
    db.add(meeting);db.flush()
    for member in members: db.add(MeetingInvitation(meeting_id=meeting.id,member_id=member,status='pending'))
    db.flush()
    return public_meeting(db,meeting,user)

def meeting_alternatives(db,meeting,invites):
    users=[db.get(User,i.member_id) for i in invites]
    start=max(dt(u.window_start) for u in users)
    end=min(dt(u.window_end) for u in users)
    free,uncomfortable={},{}
    for user in users:
        available,_,uncomfortable[user.id]=member_free(db,user.id,start.isoformat(),end.isoformat(),meeting.id if meeting.status=='confirmed' else meeting.replaces_id)
        personal=[(dt(r['start']),dt(r['end'])) for r in schedule_rows(db,latest(db,user.id))]
        free[user.id]=subtract(available,personal)
    slots=candidates(free,round((dt(meeting.end)-dt(meeting.start)).total_seconds()/60),uncomfortable)
    slots=[s for s in slots if s['start']!=meeting.start]
    return {'candidates':slots[:12],'diagnostics':[] if slots else ['当前计划窗口内没有可同时保留所有个人任务的会议备选时间，请扩大可用时间或手动协调。'],'requires_confirmation':True}

def respond(db,user,meeting_id,data):
    meeting=db.get(Meeting,meeting_id)
    if not meeting: raise HTTPException(404,'会议不存在')
    invites=invitations(db,meeting)
    invite=next((i for i in invites if i.member_id==user.id),None)
    if not invite: raise HTTPException(403,'不能代替其他成员确认')
    if data.revision!=meeting.revision: raise HTTPException(409,'邀请版本已变化')
    if meeting.status!='pending':
        if invite.status==data.response: return public_meeting(db,meeting,user)
        raise HTTPException(409,'会议已离开待确认状态，请发起新的邀请')
    if invite.status!='pending' and invite.status!=data.response: raise HTTPException(409,'已提交答复，请由发起人重新邀请')
    invite.status=data.response;db.flush()
    if data.response=='declined': meeting.status='declined'
    elif all(i.status=='accepted' for i in invites):
        if meeting.replaces_id:
            old=db.get(Meeting,meeting.replaces_id)
            if old.status!='confirmed': raise HTTPException(409,'原会议已改期，请重新邀请')
        try:
            ensure_free(db,[i.member_id for i in invites],meeting.start,meeting.end,meeting.replaces_id)
        except HTTPException:
            meeting.status='needs_reschedule'
            meeting.linkage=[{'status':'blocked','reason':'成员固定日程在邀请后发生变化，需要重新协调与确认。'}]
            db.flush();return public_meeting(db,meeting,user)
        results=[]
        for i in invites:
            member=db.get(User,i.member_id)
            result=compute(db,member,[(dt(meeting.start),dt(meeting.end))],meeting.replaces_id)
            results.append((member,result))
        failed=[(u,r) for u,r in results if r['status'] not in ('optimal','feasible')]
        if failed:
            meeting.status='needs_reschedule'
            meeting.linkage=[{'member_id':u.id,'status':'blocked','reason':'个人任务无法在原约束内调整，请生成会议备选时间并重新邀请。'} for u,r in failed]
            meeting.linkage=meeting.linkage+[{'status':'alternatives','reason':'已排除成员当前任务，生成无需挪动任务的备选；新时间仍须全员确认。',**meeting_alternatives(db,meeting,invites)}]
        else:
            meeting.status='confirmed'
            meeting.linkage=[]
            for member,result in results:
                saved=persist(db,member,result,f'所有成员同意会议 #{meeting.id}，自动修复个人任务') if result['changes'] else None
                meeting.linkage=meeting.linkage+[{'member_id':member.id,'status':'repaired' if result['changes'] else 'unchanged','changed_count':len(result['changes']),'plan_id':saved['id'] if saved else None,'reason':'保留其他任务，仅调整冲突或受依赖影响的任务。' if result['changes'] else '个人计划无冲突。'}]
            if meeting.replaces_id: db.get(Meeting,meeting.replaces_id).status='superseded'
    db.flush()
    return public_meeting(db,meeting,user)
