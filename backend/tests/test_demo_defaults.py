from sqlalchemy import select,func
from sqlalchemy.orm import sessionmaker
from app.db import Base,make_engine
from app.demo import seed
from app.models import BusyInterval,Task,User,Availability,PlanVersion,ScheduledTask

def test_default_initialization_has_no_sample_schedule(tmp_path):
    engine=make_engine('sqlite:///'+str(tmp_path/'no-courses.db'))
    Base.metadata.create_all(engine)
    factory=sessionmaker(engine)
    with factory() as db:
        seed(db)
        for model in (BusyInterval,Task,Availability,PlanVersion,ScheduledTask):
            assert db.scalar(select(func.count()).select_from(model))==0
        assert db.scalar(select(func.count()).select_from(User))==4
    engine.dispose()
