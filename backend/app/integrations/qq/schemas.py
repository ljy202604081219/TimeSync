from typing import Literal
from pydantic import Field,field_validator
from ...schemas import Strict
from ...timeutil import iso

class GroupInput(Strict):
    group_id: str=Field(pattern=r'^\d{1,20}$')
    bot_id: str=Field(default='synthetic',pattern=r'^(synthetic|\d{1,20})$')
    name: str=Field(min_length=1,max_length=100)
    consent: Literal[True]
    enabled: bool=True
    synthetic: bool=True
    ai_images: bool=False
    retention_days: int=Field(default=3,ge=1,le=30)

class GroupPatch(Strict):
    name: str | None=Field(default=None,min_length=1,max_length=100)
    consent: bool | None=None
    enabled: bool | None=None
    ai_images: bool | None=None
    retention_days: int | None=Field(default=None,ge=1,le=30)

class Event(Strict):
    # OneBot extensions are ignored at the adapter boundary, not stored.
    model_config={'extra':'ignore'}
    post_type: Literal['message','message_sent','meta_event']
    message_type: str=''
    meta_event_type: str=''
    self_id: str | int=''
    group_id: str | int=''
    user_id: str | int=''
    target_id: str | int=''
    message_id: str | int=''
    time: int=Field(ge=1,le=4102444800)
    message: str | list=Field(default_factory=list)
    raw_message: str=Field(default='',max_length=16000)
    status: dict=Field(default_factory=dict)

class Extraction(Strict):
    model_config={'extra':'forbid','strict':True}
    category: Literal['assignment','exam','report','course','course_change','meeting','registration','important','chat']
    entry_type: Literal['task','event','notice','uncertain']='uncertain'
    title: str=Field(max_length=160)
    operation: Literal['new','update','cancel','ignore']='new'
    related_title: str=Field(default='',max_length=160)
    deadline: str | None=None
    start: str | None=None
    end: str | None=None
    location: str | None=Field(default=None,max_length=200)
    confidence: float=Field(ge=0,le=1)
    importance: Literal['high','normal','low']='normal'
    evidence: str=Field(default='',max_length=1000)
    ambiguities: list[str]=Field(default_factory=list,max_length=12)
    @field_validator('deadline','start','end')
    @classmethod
    def timestamp(cls,v):return iso(v) if v else None

class Confirmation(Strict):
    mode: Literal['task','event','acknowledge']='task'
    title: str | None=Field(default=None,min_length=1,max_length=160)
    deadline: str | None=None
    start: str | None=None
    end: str | None=None
    duration_minutes: int | None=Field(default=None,ge=1,le=1440)
    priority: int | None=Field(default=None,ge=1,le=3)

class SimulateInput(Strict):
    event: Event

