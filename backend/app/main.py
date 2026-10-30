from contextlib import asynccontextmanager
from pathlib import Path
import os
import json
import hashlib
from threading import RLock
from fastapi import FastAPI, Depends, Header, HTTPException, UploadFile, File, Form, Request, Query, Response
from typing import Annotated
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import Base, engine, session, SessionLocal
from .models import User,Task,BusyInterval,Availability,PlanVersion,Disruption,RequestRecord
from .schemas import TaskInput,BusyInput,AvailabilityInput,RangeInput,DisruptionInput
from .plans import rows,latest,schedule_rows,compute,persist,serialize,valid_current,snapshot
from .timeutil import dt,expand
from .demo import seed
from .schemas import CandidateInput,MeetingInput,ResponseInput
from .models import Meeting,MeetingInvitation
from .coordination import find_candidates,create_meeting,respond,public_meeting,invitations,meeting_alternatives
from . import ai
from . import ai_config
from . import timetable
from .models import TimetableImport
from .intervals import overlap
from .agenda import AgendaQuery, AgendaResponse, build_agenda
from .school_time import profile as timetable_profile

DEMO=os.getenv('DEMO_MODE','true').lower()=='true'
TOKEN_FILE=Path(__file__).resolve().parents[1]/'.demo-tokens.json'
write_lock=RLock()

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    if DEMO:
        with SessionLocal() as db:
            tokens=seed(db)
            if tokens: TOKEN_FILE.write_text(json.dumps(tokens),encoding='utf8')
    yield

app = FastAPI(title='TimeSync 时聚', lifespan=lifespan)
@app.get('/api/health')
def health():
    return {'status':'ok', 'timezone':'Asia/Shanghai', 'slot_minutes':15}

def auth(authorization: str=Header(default=''),db:Session=Depends(session)):
    if not authorization.startswith('Bearer '): raise HTTPException(401,'请先登录演示成员或提供访问令牌')
    digest=hashlib.sha256(authorization[7:].encode()).hexdigest()
    user=db.scalar(select(User).where(User.token_hash==digest))
    if not user: raise HTTPException(401,'访问令牌无效')
    return user

def own(user,owner):
    if user.id!=owner: raise HTTPException(403,'不能读取或修改其他成员的私人日程')

def mutation(db,user,key,tag,payload,action):
    if not key or len(key)>120: raise HTTPException(400,'写操作需要 1–120 字符的 Idempotency-Key')
    fingerprint=hashlib.sha256(json.dumps([tag,payload],sort_keys=True).encode()).hexdigest()
    # ponytail: serialize local SQLite writes; use row locks on a server DB for scale.
    with write_lock:
        owner=user.id
        db.rollback()
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
        try:
            prior=db.scalar(select(RequestRecord).where(RequestRecord.owner_id==owner,RequestRecord.key==key))
            if prior:
                if prior.fingerprint!=fingerprint: raise HTTPException(409,'幂等键已用于不同请求')
                result=prior.response
                db.rollback()
                return result
            result=action()
            db.add(RequestRecord(owner_id=owner,key=key,fingerprint=fingerprint,response=result))
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise

@app.get('/api/demo/accounts')
def demo_accounts():
    if not DEMO or not TOKEN_FILE.exists(): raise HTTPException(404,'演示登录未启用')
    return {'demo':True,'notice':'本地合成演示数据；切换成员等同登录该演示身份。请勿用于公开部署。','accounts':json.loads(TOKEN_FILE.read_text(encoding='utf8'))}

@app.get('/api/me')
def me(user:User=Depends(auth)):
    return {'id':user.id,'name':user.name,'window_start':user.window_start,'window_end':user.window_end,'demo':DEMO,'ai_mode':'live' if os.getenv('AI_API_KEY') else 'demo'}

@app.get('/api/v1/agenda',response_model=AgendaResponse,responses={304:{'description':'日程内容未变化'}})
def agenda(query:Annotated[AgendaQuery,Query()],response:Response,if_none_match:str=Header(default=''),user:User=Depends(auth),db:Session=Depends(session)):
    body=build_agenda(db,user,query)
    tag='"'+body['revision']+'"'
    etag='W/'+tag
    headers={'ETag':etag,'Cache-Control':'private, no-cache','Vary':'Authorization'}
    if any(value.strip().removeprefix('W/') in (tag,'*') for value in if_none_match.split(',')):
        return Response(status_code=304,headers=headers)
    response.headers.update(headers)
    return body

@app.get('/api/users/{owner}/state')
def state(owner:str,user:User=Depends(auth),db:Session=Depends(session)):
    own(user,owner)
    plan=latest(db,owner)
    busy=rows(db,BusyInterval,owner)
    return {'tasks':[serialize(r) for r in rows(db,Task,owner)],'busy':[serialize(r) for r in busy],
            'busy_expanded':[{'start':a.isoformat(),'end':b.isoformat(),'title':r.title,'kind':r.kind} for r in busy for a,b in expand([r],user.window_start,user.window_end)],
            'availability':[serialize(r) for r in rows(db,Availability,owner)],'schedule':schedule_rows(db,plan),
            'plan':serialize(plan) if plan else None,'plan_valid':valid_current(db,user),
            'versions':[serialize(r) for r in db.scalars(select(PlanVersion).where(PlanVersion.owner_id==owner).order_by(PlanVersion.id.desc()))],
            'timetable_imports':[{'id':r.id,'week_start':r.week_start,'course_count':len(r.courses)} for r in db.scalars(select(TimetableImport).where(TimetableImport.owner_id==owner).order_by(TimetableImport.id.desc()))]}

def validate_dependencies(db,user,data,current=None):
    tasks=rows(db,Task,user.id)
    by={t.id:t.dependencies for t in tasks}
    if any(d not in by for d in data.dependencies): raise HTTPException(422,'前置任务不存在或不属于当前成员')
    by[current or -1]=data.dependencies
    visited=set()
    def visit(node,stack):
        if node in stack: raise HTTPException(422,'任务依赖存在循环')
        if node in visited: return
        for dep in by.get(node,[]): visit(dep,stack|{node})
        visited.add(node)
    visit(current or -1,set())

@app.post('/api/tasks')
def create_task(data:TaskInput,key:str=Header(default='',alias='Idempotency-Key'),user:User=Depends(auth),db:Session=Depends(session)):
    def action():
        validate_dependencies(db,user,data)
        item=Task(owner_id=user.id,**data.model_dump());db.add(item);db.flush()
        return serialize(item)
    return mutation(db,user,key,'task:create',data.model_dump(),action)

@app.put('/api/tasks/{task_id}')
def edit_task(task_id:int,data:TaskInput,key:str=Header(default='',alias='Idempotency-Key'),user:User=Depends(auth),db:Session=Depends(session)):
    def action():
        item=db.get(Task,task_id)
        if not item: raise HTTPException(404,'任务不存在')
        own(user,item.owner_id);validate_dependencies(db,user,data,task_id)
        for name,value in data.model_dump().items(): setattr(item,name,value)
        db.flush();return serialize(item)
    return mutation(db,user,key,f'task:{task_id}',data.model_dump(),action)

@app.put('/api/settings/window')
def update_window(data:RangeInput,key:str=Header(default='',alias='Idempotency-Key'),user:User=Depends(auth),db:Session=Depends(session)):
    def action():
        user.window_start,user.window_end=data.start,data.end
        db.flush();return {'start':data.start,'end':data.end}
    return mutation(db,user,key,'settings',data.model_dump(),action)

@app.post('/api/busy')
def add_busy(data:BusyInput,key:str=Header(default='',alias='Idempotency-Key'),user:User=Depends(auth),db:Session=Depends(session)):
    def action():
        item=BusyInterval(owner_id=user.id,**data.model_dump());db.add(item);db.flush();return serialize(item)
    return mutation(db,user,key,'busy',data.model_dump(),action)

@app.post('/api/availability')
def add_available(data:AvailabilityInput,key:str=Header(default='',alias='Idempotency-Key'),user:User=Depends(auth),db:Session=Depends(session)):
    def action():
        item=Availability(owner_id=user.id,**data.model_dump());db.add(item);db.flush();return serialize(item)
    return mutation(db,user,key,'availability',data.model_dump(),action)

@app.delete('/api/constraints/{kind}/{item_id}')
def delete_constraint(kind:str,item_id:int,key:str=Header(default='',alias='Idempotency-Key'),user:User=Depends(auth),db:Session=Depends(session)):
    def action():
        cls={'busy':BusyInterval,'availability':Availability}.get(kind)
        if not cls: raise HTTPException(404,'约束类型不存在')
        item=db.get(cls,item_id)
        if not item: raise HTTPException(404,'约束不存在')
        own(user,item.owner_id)
        if cls==BusyInterval and db.scalar(select(Disruption).where(Disruption.busy_id==item.id)): raise HTTPException(409,'突发事件已关联历史版本，请保留审计记录')
        db.delete(item);return {'deleted':item_id}
    return mutation(db,user,key,f'delete:{kind}:{item_id}',{},action)

@app.post('/api/plans')
def generate_plan(key:str=Header(default='',alias='Idempotency-Key'),user:User=Depends(auth),db:Session=Depends(session)):
    return mutation(db,user,key,'plan',{},lambda:persist(db,user,compute(db,user),'用户确认生成个人计划'))

@app.get('/api/plans/{plan_id}')
def get_plan(plan_id:int,user:User=Depends(auth),db:Session=Depends(session)):
    plan=db.get(PlanVersion,plan_id)
    if not plan: raise HTTPException(404,'版本不存在')
    own(user,plan.owner_id)
    return {**serialize(plan),'schedule':schedule_rows(db,plan)}

def repair(db,user,data):
    result=compute(db,user,[(dt(data.start),dt(data.end))])
    meetings=db.scalars(select(Meeting).join(MeetingInvitation).where(MeetingInvitation.member_id==user.id,Meeting.status=='confirmed'))
    result['meeting_conflicts']=[{'id':m.id,'title':m.title,'reason':'突发事件与已确认会议冲突；会议保持原时间，须由发起人重新邀请所有成员。'} for m in meetings if overlap(dt(data.start),dt(data.end),dt(m.start),dt(m.end))]
    return result

@app.post('/api/disruptions/preview')
def preview_repair(data:DisruptionInput,user:User=Depends(auth),db:Session=Depends(session)):
    return repair(db,user,data)

@app.post('/api/disruptions')
def commit_repair(data:DisruptionInput,key:str=Header(default='',alias='Idempotency-Key'),user:User=Depends(auth),db:Session=Depends(session)):
    def action():
        old=latest(db,user.id)
        if data.expected_plan_id!=(old.id if old else None) or data.expected_snapshot!=snapshot(db,user):
            raise HTTPException(409,'计划或约束已变化，请重新预览修复')
        result=repair(db,user,data)
        busy=BusyInterval(owner_id=user.id,title=data.title,start=data.start,end=data.end,kind='disruption')
        db.add(busy);db.flush()
        saved=persist(db,user,result,'突发事件：'+data.title)
        db.add(Disruption(owner_id=user.id,busy_id=busy.id,plan_id=saved['id'],description=data.title))
        return saved
    return mutation(db,user,key,'disruption',data.model_dump(),action)

async def read_image(image):
    raw=None;mime=None
    if image:
        raw=await image.read(6*1024*1024+1)
        await image.close()
        if len(raw)>6*1024*1024: raise HTTPException(413,'截图最大为 6 MB')
        if raw.startswith(b'\x89PNG\r\n\x1a\n'): mime='image/png'
        elif raw.startswith(b'\xff\xd8\xff'): mime='image/jpeg'
        elif raw[:4]==b'RIFF' and raw[8:12]==b'WEBP': mime='image/webp'
        else: raise HTTPException(422,'仅支持有效的 PNG / JPEG / WebP 截图')
    return raw,mime

@app.post('/api/extract')
async def extract_notice(text:str=Form(default='',max_length=12000),image:UploadFile|None=File(default=None),user:User=Depends(auth)):
    raw,mime=await read_image(image)
    if not text.strip() and not raw: raise HTTPException(422,'请输入通知文本或上传截图')
    try:
        return await ai.extract(text,raw,mime)
    except Exception as error:
        raise HTTPException(502,ai_config.explain(error)+' 未保存任何任务，可重试或手动录入。')

@app.post('/api/timetable/extract')
async def extract_courses(image:UploadFile=File(),notes:str=Form(default='',max_length=6000),use_school_schedule:bool=Form(default=True),user:User=Depends(auth)):
    raw,mime=await read_image(image)
    try:
        return await timetable.extract_timetable(raw,mime,notes,use_school_schedule)
    except Exception as error:
        raise HTTPException(502,ai_config.explain(error)+' 未导入任何课程，请重试或手动填写。')

@app.get('/api/timetable/profile')
def school_profile(user:User=Depends(auth)):
    return timetable_profile()

@app.post('/api/timetable/preview')
def preview_courses(data:timetable.ImportInput,user:User=Depends(auth),db:Session=Depends(session)):
    return timetable.preview(db,user,data)

@app.post('/api/timetable/import')
def save_courses(data:timetable.ImportInput,key:str=Header(default='',alias='Idempotency-Key'),user:User=Depends(auth),db:Session=Depends(session)):
    return mutation(db,user,key,'timetable:import',data.model_dump(mode='json'),lambda:timetable.import_courses(db,user,data))

@app.get('/api/timetable/imports')
def course_imports(user:User=Depends(auth),db:Session=Depends(session)):
    return [serialize(r) for r in rows(db,TimetableImport,user.id)]

@app.post('/api/coordination/candidates')
def coordination(data:CandidateInput,user:User=Depends(auth),db:Session=Depends(session)):
    if user.id not in data.members: raise HTTPException(403,'只能参与本人所属的协调')
    return find_candidates(db,data)

@app.get('/api/meetings')
def meetings(user:User=Depends(auth),db:Session=Depends(session)):
    items=db.scalars(select(Meeting).join(MeetingInvitation).where(MeetingInvitation.member_id==user.id).order_by(Meeting.id.desc()))
    return [public_meeting(db,m,user) for m in items]

@app.post('/api/meetings')
def invite_meeting(data:MeetingInput,key:str=Header(default='',alias='Idempotency-Key'),user:User=Depends(auth),db:Session=Depends(session)):
    return mutation(db,user,key,'meeting',data.model_dump(),lambda:create_meeting(db,user,data))

@app.post('/api/meetings/{meeting_id}/respond')
def answer(meeting_id:int,data:ResponseInput,key:str=Header(default='',alias='Idempotency-Key'),user:User=Depends(auth),db:Session=Depends(session)):
    return mutation(db,user,key,f'respond:{meeting_id}',data.model_dump(),lambda:respond(db,user,meeting_id,data))

@app.patch('/api/meetings/{meeting_id}')
def reject_direct_edit(meeting_id:int,user:User=Depends(auth),db:Session=Depends(session)):
    meeting=db.get(Meeting,meeting_id)
    if not meeting: raise HTTPException(404,'会议不存在')
    if meeting.organizer_id!=user.id: raise HTTPException(403,'只有会议发起人可以提出新的邀请')
    raise HTTPException(409,'会议时间不可直接修改，请创建关联原会议的新邀请；所有成员确认前原会议保持有效')

@app.get('/api/meetings/{meeting_id}/alternatives')
def meeting_slots(meeting_id:int,user:User=Depends(auth),db:Session=Depends(session)):
    meeting=db.get(Meeting,meeting_id)
    if not meeting: raise HTTPException(404,'会议不存在')
    public_meeting(db,meeting,user)
    return meeting_alternatives(db,meeting,invitations(db,meeting))

def local_ai_admin(request:Request,user:User=Depends(auth)):
    # This is a workstation configuration screen, never a production admin API.
    if not DEMO or user.id!='A': raise HTTPException(403,'只有本地演示管理员 A 可配置模型。')
    from urllib.parse import urlsplit
    if not request.client or request.client.host not in ('127.0.0.1','::1','testclient'):
        raise HTTPException(403,'模型配置只允许本机访问。')
    origin=request.headers.get('origin')
    if origin and (urlsplit(origin).hostname not in ('127.0.0.1','localhost','::1') or origin.rstrip('/')!=str(request.base_url).rstrip('/')):
        raise HTTPException(403,'拒绝跨来源模型配置请求。')
    return user

@app.get('/api/ai/settings')
def ai_settings(user:User=Depends(local_ai_admin)):
    return ai_config.status()

@app.post('/api/ai/test-and-save')
async def ai_connect(data:ai_config.SettingsInput,user:User=Depends(local_ai_admin)):
    try:
        return await ai_config.test_and_save(data)
    except ValueError:
        # Never return provider response bodies, request headers or credential data.
        raise HTTPException(400,'配置无效或测试返回不符合要求的 JSON；请核对地址、模型和 Key。')
    except Exception as error:
        raise HTTPException(502,ai_config.explain(error)+' 原配置保持不变。')

@app.post('/api/ai/demo')
def ai_use_demo(user:User=Depends(local_ai_admin)):
    ai_config.save({'AI_API_KEY':''})
    return ai_config.status()

# Production launcher builds first, then serves UI and API from one origin.
DIST=Path(__file__).resolve().parents[2]/'frontend'/'dist'
if DIST.exists():
    app.mount('/',StaticFiles(directory=str(DIST),html=True),name='frontend')
