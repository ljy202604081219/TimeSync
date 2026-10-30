"""Synthetic, repeatable demo fixtures. No real student data."""
import hashlib
import secrets
from .models import User,Task,BusyInterval,Availability,PlanVersion,ScheduledTask

DEMO_START='2026-11-02T08:00:00+08:00'
DEMO_END='2026-11-09T08:00:00+08:00'
def stamp(day,time): return f'2026-11-{day:02}T{time}:00+08:00'

def seed(db,*,demo_data=False):
    if db.get(User,'A'): return None
    tokens={}
    for index,member in enumerate('ABCD'):
        token=secrets.token_urlsafe(32);tokens[member]=token
        user=User(id=member,name={'A':'林同学','B':'陈同学','C':'王同学','D':'许同学'}[member],token_hash=hashlib.sha256(token.encode()).hexdigest(),window_start=DEMO_START,window_end=DEMO_END)
        db.add(user);db.flush()
        if not demo_data: continue
        for day in range(2,9):
            db.add(Availability(owner_id=member,start=stamp(day,'08:00'),end=stamp(day,'22:00'),kind='available'))
            db.add(Availability(owner_id=member,start=stamp(day,'12:00'),end=stamp(day,'13:30'),kind='uncomfortable'))
        courses=[(2,'08:00','10:00','高等数学'),(3,'10:00','12:00','程序设计'),(4,'08:00','10:00','大学英语'),(5,'14:00','16:00','专业选修'),(6,'10:00','12:00','通识课程')]
        for day,a,b,title in courses:
            hour_shift=index if day in (2,4) else 0
            a=f'{int(a[:2])+hour_shift:02}:00';b=f'{int(b[:2])+hour_shift:02}:00'
            db.add(BusyInterval(owner_id=member,title=title,start=stamp(day,a),end=stamp(day,b),kind='course',weekday=day-2))
        first=Task(owner_id=member,title='机器学习 · 实验报告',deadline=stamp(5,'18:00'),duration_minutes=120,priority=3,requirements='提交 PDF 与源代码',source='demo',dependencies=[])
        db.add(first);db.flush()
        second=Task(owner_id=member,title='阅读与整理文献',deadline=stamp(6,'20:00'),duration_minutes=90,priority=2,dependencies=[],source='demo')
        third=Task(owner_id=member,title='小组项目 · 演示准备',deadline=stamp(8,'20:00'),duration_minutes=60,priority=2,dependencies=[first.id],source='demo')
        db.add_all([second,third]);db.flush()
        plan=PlanVersion(owner_id=member,parent_id=None,reason='四人演示初始计划（合成数据）',created_at=stamp(2,'08:00'),status='feasible',changes=[],diagnostics=[])
        db.add(plan);db.flush()
        for task,a,b in [(first,stamp(4,'14:00'),stamp(4,'16:00')),(second,stamp(5,'09:00'),stamp(5,'10:30')),(third,stamp(6,'16:00'),stamp(6,'17:00'))]:
            db.add(ScheduledTask(plan_id=plan.id,task_id=task.id,start=a,end=b))
    db.commit()
    return tokens
