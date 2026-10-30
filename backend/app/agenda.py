"""Owner-scoped, bounded read model shared by the web calendar and device clients."""
from datetime import timedelta
import hashlib
import json
from typing import Literal
from pydantic import Field, model_validator
from sqlalchemy import select
from .schemas import Strict, RangeInput
from .models import Task, BusyInterval, Meeting, MeetingInvitation, PlanVersion
from .plans import rows, latest, schedule_rows, valid_current
from .timeutil import dt, now, expand
from .intervals import overlap


class AgendaQuery(Strict):
    start: str | None = None
    end: str | None = None
    limit: int = Field(default=12, ge=1, le=50)

    @model_validator(mode='after')
    def window(self):
        if (self.start is None) != (self.end is None):
            raise ValueError('start 和 end 必须一起提供，或都不提供以读取服务器今天的日程')
        if self.start is None:
            today=dt(now()).replace(hour=0,minute=0,second=0,microsecond=0)
            self.start,self.end=today.isoformat(),(today+timedelta(days=1)).isoformat()
        value=RangeInput(start=self.start,end=self.end)
        if dt(value.end)-dt(value.start)>timedelta(days=7):
            raise ValueError('日程读取范围最多 7 天')
        self.start,self.end=value.start,value.end
        return self


class AgendaEvent(Strict):
    id: str
    kind: Literal['course','unavailable','disruption','task','meeting','deadline']
    source_id: int
    title: str
    start: str
    end: str
    status: Literal['fixed','scheduled','stale','confirmed','due']


class AgendaInvitation(Strict):
    meeting_id: int
    title: str
    start: str
    end: str
    revision: int


class AgendaPlan(Strict):
    id: int | None
    valid: bool
    repair_needed: bool
    latest_attempt_status: str | None


class AgendaResponse(Strict):
    schema_version: Literal[1] = 1
    revision: str
    server_time: str
    timezone: Literal['Asia/Shanghai'] = 'Asia/Shanghai'
    user_id: str
    start: str
    end: str
    plan: AgendaPlan
    events: list[AgendaEvent]
    event_total: int
    truncated: bool
    pending_invitations: list[AgendaInvitation]
    pending_total: int


def build_agenda(db,user,query):
    start,end=dt(query.start),dt(query.end)
    plan=latest(db,user.id)
    valid=valid_current(db,user)
    tasks=rows(db,Task,user.id)
    events=[]
    def event(kind,source_id,title,a,b,status):
        events.append({'id':f'{kind}:{source_id}:{a.isoformat()}','kind':kind,'source_id':source_id,
                       'title':title[:80],'start':a.isoformat(),'end':b.isoformat(),'status':status})
    # Expand full days, then filter, so a query midway through a class preserves
    # its actual start/end rather than reporting the clipped query boundary.
    day_start=start.replace(hour=0,minute=0,second=0,microsecond=0)
    day_end=end.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
    for busy in rows(db,BusyInterval,user.id):
        ranges=expand([busy],day_start,day_end) if busy.weekday is not None else [(dt(busy.start),dt(busy.end))]
        for a,b in ranges:
            if overlap(a,b,start,end): event(busy.kind,busy.id,busy.title,a,b,'fixed')
    for item in schedule_rows(db,plan):
        a,b=dt(item['start']),dt(item['end'])
        if overlap(a,b,start,end): event('task',item['task_id'],item['title'],a,b,'scheduled' if valid else 'stale')
    for task in tasks:
        deadline=dt(task.deadline)
        if start<=deadline<end: event('deadline',task.id,task.title,deadline,deadline,'due')
    meetings=db.scalars(select(Meeting).join(MeetingInvitation).where(MeetingInvitation.member_id==user.id))
    pending=[]
    for meeting in meetings:
        a,b=dt(meeting.start),dt(meeting.end)
        if meeting.status=='confirmed' and overlap(a,b,start,end):
            event('meeting',meeting.id,meeting.title,a,b,'confirmed')
        if meeting.status=='pending':
            invite=db.scalar(select(MeetingInvitation).where(MeetingInvitation.meeting_id==meeting.id,MeetingInvitation.member_id==user.id))
            if invite.status=='pending':
                pending.append({'meeting_id':meeting.id,'title':meeting.title[:80],'start':meeting.start,'end':meeting.end,'revision':meeting.revision})
    events.sort(key=lambda e:(e['start'],e['kind'],e['source_id']))
    pending.sort(key=lambda i:(i['start'],i['meeting_id']))
    attempt=db.scalar(select(PlanVersion).where(PlanVersion.owner_id==user.id).order_by(PlanVersion.id.desc()))
    body={'schema_version':1,'timezone':'Asia/Shanghai','user_id':user.id,'start':query.start,'end':query.end,
          'plan':{'id':plan.id if plan else None,'valid':valid,'repair_needed':bool(tasks) and not valid,'latest_attempt_status':attempt.status if attempt else None},
          'events':events[:query.limit],'event_total':len(events),'truncated':len(events)>query.limit,
          'pending_invitations':pending[:12],'pending_total':len(pending)}
    # Server time is excluded: an unchanged representation can return HTTP 304.
    revision=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {**body,'revision':revision,'server_time':now()}
