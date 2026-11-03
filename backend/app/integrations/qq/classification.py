"""One recommendation for new AI results and legacy notices, without DB writes."""
import re


def recommendation(category,extraction,title='',deadline=None,operation='new',has_task=False):
    if operation=='cancel':return {'mode':'acknowledge','busy_kind':'unavailable'}
    if has_task:return {'mode':'task','busy_kind':'unavailable'}
    text=title+'\n'+(extraction.get('evidence') or '')
    submission=bool(re.search(r'提交|上交|截止|DDL|交作业|交报告|交.{0,8}(作业|报告)',text,re.I))
    course=category in ('course','course_change') or (not deadline and not submission and bool(re.search(r'上课|开课|上.{0,16}课|第[一二三四五六七八九十\d]+[—到至\-~～]?[一二三四五六七八九十\d]*节|课程安排',text)))
    entry=extraction.get('entry_type','uncertain')
    if entry=='task':mode='task'
    elif entry=='event':mode='event'
    elif entry=='notice':mode='acknowledge'
    elif course or category in ('exam','meeting'):mode='event'
    elif deadline:mode='task'
    elif extraction.get('start') or extraction.get('end'):mode='event'
    elif submission or category in ('assignment','report','registration'):mode='task'
    elif category=='chat':mode='acknowledge'
    else:mode=''  # Uncertain notifications should not silently become DDL tasks.
    return {'mode':mode,'busy_kind':'course' if course else 'unavailable'}
