from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
def dt(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if value.tzinfo is None:
        raise ValueError('时间必须包含时区，例如 +08:00')
    return value.astimezone(TZ)

def iso(value):
    return dt(value).isoformat(timespec='seconds')

def now():
    return datetime.now(TZ).isoformat(timespec='seconds')

def expand(rows, start, end):
    """Expand concrete or weekly half-open intervals; clip to the planning window."""
    start, end = dt(start), dt(end)
    out = []
    for row in rows:
        a, b = dt(row.start), dt(row.end)
        if row.weekday is None:
            candidates = [(a,b)]
        else:
            day = start.replace(hour=0, minute=0, second=0, microsecond=0)
            candidates = []
            while day < end:
                if day.weekday() == row.weekday:
                    candidates.append((day.replace(hour=a.hour,minute=a.minute,second=a.second,microsecond=a.microsecond), day.replace(hour=b.hour,minute=b.minute,second=b.second,microsecond=b.microsecond)))
                day += timedelta(days=1)
        for a,b in candidates:
            a,b = max(a,start),min(b,end)
            if a < b:
                out.append((a,b))
    return out
