"""Export actual API schemas and synthetic integration data; never uses the live DB/API."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db import Base, make_engine
from app.demo import seed
from app.models import User
from app.agenda import AgendaQuery, AgendaResponse, build_agenda
from app.coordination import create_meeting, respond
from app.schemas import MeetingInput, ResponseInput
from app.school_time import profile


def main():
    target=Path(__file__).resolve().parents[1]/'docs'/'contracts'
    target.mkdir(parents=True,exist_ok=True)
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
        finally:
            engine.dispose()
    for name,data in [('openapi.json',app.openapi()),('agenda.example.json',example),('timetable-profile.example.json',profile())]:
        (target/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('Exported OpenAPI and synthetic agenda example:',target)


if __name__=='__main__': main()
