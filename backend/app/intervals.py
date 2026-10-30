from datetime import timedelta

def merge(intervals):
    result=[]
    for a,b in sorted(intervals):
        if a >= b:
            continue
        if result and a <= result[-1][1]:
            result[-1]=(result[-1][0],max(b,result[-1][1]))
        else:
            result.append((a,b))
    return result

def intersect(left,right):
    left,right=merge(left),merge(right)
    i=j=0
    out=[]
    while i<len(left) and j<len(right):
        a,b=max(left[i][0],right[j][0]),min(left[i][1],right[j][1])
        if a<b:
            out.append((a,b))
        if left[i][1]<right[j][1]: i+=1
        else: j+=1
    return out

def subtract(available,busy):
    result=merge(available)
    for c,d in merge(busy):
        result=[part for a,b in result for part in ((a,min(b,c)),(max(a,d),b)) if part[0]<part[1]]
    return result

def overlap(a,b,c,d):
    return a<d and c<b

def ceil_slot(value):
    if value.second or value.microsecond:
        value=value.replace(second=0,microsecond=0)+timedelta(minutes=1)
    return value+timedelta(minutes=(-value.minute)%15)


def candidates(free_by_member, duration_minutes, uncomfortable=None, preferred=None):
    common=None
    for ranges in free_by_member.values():
        common=merge(ranges) if common is None else intersect(common,ranges)
    results=[]
    step=timedelta(minutes=15)
    duration=timedelta(minutes=duration_minutes)
    for a,b in common or []:
        # Snap UP; never extend a slot outside a member's available interval.
        a=ceil_slot(a)
        while a+duration<=b:
            conflicts=sum(any(overlap(a,a+duration,c,d) for c,d in ranges) for ranges in (uncomfortable or {}).values())
            preference=abs((a-preferred).total_seconds())/60 if preferred else 0
            results.append({'start':a.isoformat(),'end':(a+duration).isoformat(),'uncomfortable_members':conflicts,'preference_distance':preference})
            a+=step
    return sorted(results,key=lambda x:(x['uncomfortable_members'],x['preference_distance'],x['start']))
