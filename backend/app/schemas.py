from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from .timeutil import iso, dt

class Strict(BaseModel):
    model_config={'extra':'forbid'}

class TaskInput(Strict):
    title: str = Field(min_length=1,max_length=160)
    deadline: str
    duration_minutes: int = Field(ge=15,le=1440,multiple_of=15)
    priority: int = Field(default=2,ge=1,le=3)
    dependencies: list[int] = Field(default_factory=list,max_length=60)
    requirements: str = Field(default='',max_length=4000)
    evidence: str = Field(default='',max_length=8000)
    source: Literal['manual','demo','ai']='manual'
    @field_validator('deadline')
    @classmethod
    def time(cls,v): return iso(v)
    @field_validator('title')
    @classmethod
    def title_text(cls,v):
        if not v.strip(): raise ValueError('任务名称不能为空')
        return v.strip()

class RangeInput(Strict):
    start: str
    end: str
    @field_validator('start','end')
    @classmethod
    def time(cls,v): return iso(v)
    @model_validator(mode='after')
    def order(self):
        if dt(self.start)>=dt(self.end): raise ValueError('结束时间必须晚于开始时间')
        if (dt(self.end)-dt(self.start)).total_seconds()>14*86400: raise ValueError('范围不得超过 14 天')
        return self

class BusyInput(RangeInput):
    title: str = Field(min_length=1,max_length=160)
    weekday: int | None = Field(default=None,ge=0,le=6)
    kind: Literal['course','unavailable']='course'
    @model_validator(mode='after')
    def same_day(self):
        if self.weekday is not None and dt(self.start).date()!=dt(self.end).date():
            raise ValueError('每周重复时段须在同一天内')
        return self

class AvailabilityInput(RangeInput):
    kind: Literal['available','uncomfortable']='available'
    weekday: int | None = Field(default=None,ge=0,le=6)
    @model_validator(mode='after')
    def same_day(self):
        if self.weekday is not None and dt(self.start).date()!=dt(self.end).date():
            raise ValueError('每周重复时段须在同一天内')
        return self

class DisruptionInput(RangeInput):
    title: str = Field(min_length=1,max_length=160)
    expected_plan_id: int | None = None
    expected_snapshot: str | None = None

class CandidateInput(RangeInput):
    duration_minutes: int = Field(default=60,ge=15,le=480,multiple_of=15)
    members: list[str] = Field(default_factory=lambda:['A','B','C','D'],min_length=1,max_length=4)
    preferred: str | None = None
    @field_validator('members')
    @classmethod
    def unique(cls,v): return sorted(set(v))
    @field_validator('preferred')
    @classmethod
    def pref(cls,v): return iso(v) if v else None

class MeetingInput(RangeInput):
    title: str = Field(min_length=1,max_length=160)
    members: list[str] = Field(default_factory=lambda:['A','B','C','D'],min_length=1,max_length=4)
    replaces_id: int | None = None

class ResponseInput(Strict):
    response: Literal['accepted','declined']
    revision: int = Field(ge=1)
