"""User-provided 湖大 timetable defaults; not used for notification DDL parsing."""
import re

PERIODS=[('08:00','08:45'),('08:55','09:40'),('10:00','10:45'),('10:55','11:40'),
         ('14:30','15:15'),('15:15','16:00'),('16:10','16:55'),('16:55','17:40'),
         ('19:00','19:45'),('19:55','20:40'),('20:50','21:35')]


def profile():
    return {'id':'huda','label':'湖大作息（按你的设置）',
            'periods':[{'number':i,'start':a,'end':b} for i,(a,b) in enumerate(PERIODS,1)],
            'evening_start':'19:00','evening_end':'21:35',
            'notice':'仅有节次时按此表换算；按你的晚课规则，19:00开始的课程默认至21:35。原文时间保留在证据中，导入前均可修改。'}


def apply_defaults(row):
    """Map original period evidence deterministically; never invent an unseen course."""
    evidence=row.evidence.replace('：',':')
    clocks=re.findall(r'(?<!\d)([0-2]?\d:[0-5]\d)(?!\d)',evidence)
    clocks=[value.zfill(5) for value in clocks]
    first,last=row.period_start,row.period_end
    # Older compatible models may omit the new period fields.
    match=re.search(r'(?:第)?(\d{1,2})\s*(?:[-—–~～至到]\s*(?:第)?(\d{1,2}))?\s*节',evidence)
    if match:
        first=int(match[1]);last=int(match[2] or match[1])
    elif first is not None and last is None:
        last=first
    if first is not None and last is not None and not (1<=first<=last<=11):
        row.start_time=row.end_time=None
        row.ambiguities.append('节次范围无效，请核对后手动填写。')
        return
    if first is not None and last is not None and not clocks:
        row.period_start,row.period_end=first,last
        row.start_time,row.end_time=PERIODS[first-1][0],PERIODS[last-1][1]
        row.time_basis=f'湖大默认作息：第{first}–{last}节，{row.start_time}–{row.end_time}，请核对。'
    elif '19:00' in clocks and row.start_time is None:
        row.start_time='19:00'
    # User explicitly requests the full evening block for any 19:00 class.
    if row.start_time=='19:00':
        row.end_time='21:35'
        row.time_basis='按你的湖大晚课规则默认19:00–21:35；如本次时长不同，请在确认页修改。'
