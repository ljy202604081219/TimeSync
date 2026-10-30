import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from app.db import Base,make_engine,session
from app.main import app
from app.demo import seed

@pytest.fixture
def system(tmp_path):
    engine=make_engine('sqlite:///'+str(tmp_path/'test.db'))
    Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    with factory() as db: tokens=seed(db,demo_data=True)
    def override():
        with factory() as db: yield db
    app.dependency_overrides[session]=override
    client=TestClient(app)
    def call(method,path,member='A',key=None,**kwargs):
        import uuid
        headers={'Authorization':'Bearer '+tokens[member],'Idempotency-Key':key or str(uuid.uuid4())}
        return client.request(method,path,headers=headers,**kwargs)
    yield call,factory,client
    app.dependency_overrides.clear()
    engine.dispose()
