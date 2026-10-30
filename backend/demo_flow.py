"""Isolated, repeatable end-to-end demonstration. No live model or default DB required."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from app.db import Base,make_engine,session
from app.main import app
from app.demo import seed
from app.models import User
from app.plans import valid_current

def main():
    evidence=[]
    with TemporaryDirectory() as folder:
        engine=make_engine('sqlite:///'+str(Path(folder)/'demo.db'))
        Base.metadata.create_all(engine)
        factory=sessionmaker(engine,expire_on_commit=False)
        with factory() as db: tokens=seed(db,demo_data=True)
        def override():
            with factory() as db: yield db
        app.dependency_overrides[session]=override
        client=TestClient(app)
        counter=0
        def call(method,path,member='A',**kwargs):
            nonlocal counter
            counter+=1
            response=client.request(method,path,headers={'Authorization':'Bearer '+tokens[member],'Idempotency-Key':f'demo-{counter}'},**kwargs)
            assert response.status_code==200,response.text
            return response.json()
        # Explicitly force the local rule demonstration, even if the machine has a key.
        import os
        previous_key=os.environ.pop('AI_API_KEY',None)
        try:
            extracted=call('POST','/api/extract',data={'text':'机器学习 · 实验二报告\n2026年11月5日18:00前提交 PDF 和代码。'})
        finally:
            if previous_key: os.environ['AI_API_KEY']=previous_key
        assert extracted['mode']=='demo'
        data=extracted['data']
        task=call('POST','/api/tasks',json={'title':data['title'],'deadline':data['deadline'],'duration_minutes':60,'priority':2,'requirements':data['requirements'],'evidence':data['evidence'],'source':'demo'})
        evidence.append({'step':'DDL 规则提取 → 人工确认保存','mode':extracted['mode'],'task_id':task['id'],'deadline':task['deadline']})
        plan=call('POST','/api/plans')
        assert plan['status']=='optimal'
        evidence.append({'step':'个人排程','version':plan['id'],'status':plan['status'],'task_count':len(plan['schedule'])})
        common=call('POST','/api/coordination/candidates',json={'start':'2026-11-04T13:00:00+08:00','end':'2026-11-04T20:00:00+08:00','duration_minutes':60})
        chosen=next(c for c in common['candidates'] if c['start']=='2026-11-04T14:00:00+08:00')
        meeting=call('POST','/api/meetings',json={'title':'四人项目讨论','start':chosen['start'],'end':chosen['end'],'members':['A','B','C','D']})
        statuses=[]
        for member in 'ABCD':
            meeting=call('POST',f"/api/meetings/{meeting['id']}/respond",member,json={'response':'accepted','revision':1})
            statuses.append(meeting['status'])
        assert statuses==['pending','pending','pending','confirmed']
        assert sum(r.get('changed_count',0) for r in meeting['linkage'])==4
        evidence.append({'step':'多人协调 → 全员确认 → 四人个人计划联动修复','candidate_count':common['total'],'meeting_id':meeting['id'],'states':statuses,'linkage':meeting['linkage']})
        agenda_query={'start':'2026-11-04T00:00:00+08:00','end':'2026-11-06T00:00:00+08:00'}
        agenda_before=call('GET','/api/v1/agenda',params=agenda_query)
        assert agenda_before['plan']['valid'] and any(e['kind']=='meeting' for e in agenda_before['events'])
        event={'title':'周三临时增加实验','start':'2026-11-04T15:00:00+08:00','end':'2026-11-04T17:00:00+08:00'}
        preview=call('POST','/api/disruptions/preview',json=event)
        assert preview['changes'] and preview['status']=='optimal'
        saved=call('POST','/api/disruptions',json={**event,'expected_plan_id':preview['expected_plan_id'],'expected_snapshot':preview['expected_snapshot']})
        evidence.append({'step':'突发事件 → 修复预览 → 确认新版本','version':saved['id'],'status':saved['status'],'changes':saved['changes']})
        agenda_after=call('GET','/api/v1/agenda',params=agenda_query)
        assert agenda_after['plan']['valid'] and agenda_after['revision']!=agenda_before['revision']
        assert any(e['kind']=='disruption' for e in agenda_after['events'])
        assert next(e for e in agenda_after['events'] if e['kind']=='meeting')['start']==meeting['start']
        evidence.append({'step':'前端/设备统一接口读取修复结果，已确认会议保持原时间','schema_version':agenda_after['schema_version'],'event_kinds':sorted({e['kind'] for e in agenda_after['events']}),'plan_valid':agenda_after['plan']['valid']})
        with factory() as db:
            assert all(valid_current(db,db.get(User,m)) for m in 'ABCD')
        evidence.append({'step':'最终独立硬约束验证','members':['A','B','C','D'],'passed':True})
        app.dependency_overrides.clear()
        client.close();engine.dispose()
    target=Path(__file__).resolve().parents[1]/'docs'/'demo-flow.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
    print('DEMO PASSED:',target)

if __name__=='__main__': main()
