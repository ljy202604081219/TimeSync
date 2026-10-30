"""Export actual API schemas and synthetic integration data; never uses the live DB/API."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy.orm import sessionmaker

from app import devices
from app.auth import Principal, SESSION_SCOPES
from app.agenda import AgendaQuery, AgendaResponse, build_agenda
from app.coordination import create_meeting, respond
from app.db import Base, make_engine
from app.demo import seed
from app.main import app
from app.models import DeviceToken, User
from app.schemas import MeetingInput, ResponseInput
from app.school_time import profile

REDACTED = '<token-returned-once>'
DEVICE_EXAMPLE_ID = '<device-token-id>'


def main():
    target=Path(__file__).resolve().parents[1]/'docs'/'contracts'
    target.mkdir(parents=True,exist_ok=True)
    previous=os.environ.get('SANDBOX_MODE')
    os.environ['SANDBOX_MODE']='true'
    try:
        with TemporaryDirectory() as folder:
            engine=make_engine('sqlite:///'+str(Path(folder)/'contracts.db'))
            try:
                Base.metadata.create_all(engine)
                with sessionmaker(engine,expire_on_commit=False)() as db:
                    seed(db,demo_data=True)
                    meeting=create_meeting(db,db.get(User,'A'),MeetingInput(title='合成演示 · 四人组会',start='2026-11-04T14:00:00+08:00',end='2026-11-04T16:00:00+08:00',members=list('ABCD')))
                    for member in 'ABCD':
                        result=respond(db,db.get(User,member),meeting['id'],ResponseInput(response='accepted',revision=1))
                    assert result['status']=='confirmed'
                    query=AgendaQuery(start='2026-11-04T00:00:00+08:00',end='2026-11-06T00:00:00+08:00')
                    example=AgendaResponse.model_validate(build_agenda(db,db.get(User,'A'),query)).model_dump()
                    assert {'course','task','meeting','deadline'}<={e['kind'] for e in example['events']}

                    # Synthetic examples for the endpoints added in B2. Tokens are
                    # replaced so nobody copies a working credential from the docs.
                    session=devices.create_session(db,'A','127.0.0.1')
                    session_example={**session,'token':REDACTED}
                    principal=Principal(user=db.get(User,'A'),kind='session',scope=SESSION_SCOPES,
                                        token_id='<session-id>',expires_at=session['expires_at'])
                    session_info=devices.session_info(principal)
                    device=devices.issue_device(db,'A','宿舍只读屏',7)
                    device_example={**device,'token':REDACTED,'id':DEVICE_EXAMPLE_ID,
                                    'notice':'明文令牌只在签发响应中出现一次；此处仅示意。'}
                    listed=[{**devices.device_metadata(db.get(DeviceToken,device['id'])),'id':DEVICE_EXAMPLE_ID}]
                    device_list={'devices':listed,
                                 'note':'last_request_at 只表示服务器最近收到该凭据的请求，不代表屏幕已亮或内容已绘制。'}
            finally:
                engine.dispose()
    finally:
        if previous is None:
            os.environ.pop('SANDBOX_MODE',None)
        else:
            os.environ['SANDBOX_MODE']=previous
    for name,data in [('openapi.json',app.openapi()),('agenda.example.json',example),
                      ('timetable-profile.example.json',profile()),
                      ('sandbox-session.example.json',session_example),
                      ('sandbox-session-info.example.json',session_info),
                      ('device-token.example.json',device_example),
                      ('devices.example.json',device_list)]:
        (target/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('Exported OpenAPI and synthetic examples:',target)


if __name__=='__main__': main()
