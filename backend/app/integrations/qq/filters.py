import re
from datetime import timedelta
from ...timeutil import dt
from ...assistant import _number

def obvious_chat(text,images):
    return not images and bool(re.fullmatch(r'[\s，,。.!！]*(收到|好的|好|谢谢|嗯|ok|OK|哈哈+|[\[表情\]]+)[\s，,。.!！]*',text))

def resolve_time(text,sent_at):
    """Only resolve an explicit day AND clock, anchored to the sent timestamp."""
    base=dt(sent_at).replace(hour=0,minute=0,second=0,microsecond=0)
    explicit=re.search(r'(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})日?',text)
    partial=re.search(r'(?<!\d)(\d{1,2})月(\d{1,2})日?',text)
    if explicit:
        y,m,d=map(int,explicit.groups());base=base.replace(year=y,month=m,day=d)
    elif partial:base=base.replace(month=int(partial[1]),day=int(partial[2]))
    elif '后天' in text:base+=timedelta(days=2)
    elif '明天' in text or '明晚' in text or '明早' in text:base+=timedelta(days=1)
    elif any(x in text for x in ['今天','今晚','今早']):pass
    elif week:=re.search(r'(下周|本周|这周|周|星期)([一二三四五六日天])',text):
        weekday='一二三四五六日'.index('日' if week[2]=='天' else week[2])
        shift=weekday-base.weekday()
        if week[1]=='下周':shift+=7
        elif week[1] in ('周','星期'):shift%=7
        base+=timedelta(days=shift)
    else:return None
    clock=re.search(r'(?<!\d)(\d{1,2}):([0-5]\d)',text)
    cn=re.search(r'([零一二两三四五六七八九十\d]{1,3})点(?:(半)|(一刻|三刻)|([零一二两三四五六七八九十\d]{1,3})分?)?',text)
    if clock:h,n=int(clock[1]),int(clock[2])
    elif cn:h,n=_number(cn[1]),30 if cn[2] else 15 if cn[3]=='一刻' else 45 if cn[3]=='三刻' else _number(cn[4]) if cn[4] else 0
    else:return None
    if any(w in text for w in ('下午','晚上','傍晚','今晚','明晚')) and 1<=h<12:h+=12
    return base.replace(hour=h,minute=n).isoformat()

def demo_extract(text,sent_at,images=False):
    from .schemas import Extraction
    from .classification import recommendation
    category=next((c for word,c in [('考试','exam'),('报告','report'),('作业','assignment'),('调课','course_change'),('组会','meeting'),('报名','registration'),('通知','important')] if word in text),'chat')
    operation='cancel' if '取消' in text else 'update' if any(w in text for w in ('改为','延期','更改')) else 'new'
    deadline=resolve_time(text,sent_at)
    suggestion=recommendation(category,{'evidence':text})
    event=suggestion['mode']=='event'
    if suggestion['busy_kind']=='course' and category!='course_change':category='course'
    title=re.search(r'[《「“](.*?)[》」”]',text)
    ambiguities=['规则演示，非真实AI；请核对字段。']
    if not deadline:ambiguities.append('日期或具体钟点不明确，需要手动补充。')
    if event:ambiguities.append('规则演示未解析结束时间，请核对并补充。')
    if images:ambiguities.append('规则模式不进行图片OCR。')
    return Extraction(category=category,title=title[1] if title else text[:80] or '待核对图片通知',operation=operation,
        entry_type='event' if event else 'task' if suggestion['mode']=='task' else 'uncertain',
        deadline=None if event else deadline,start=deadline if event else None,confidence=0.5,evidence=text[:1000],ambiguities=ambiguities)
