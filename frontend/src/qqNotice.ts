type Notice={suggested_mode?:string;operation?:string;category?:string;deadline?:string|null;current_task?:unknown;extraction?:{entry_type?:string;start?:string|null;end?:string|null}};
export type ConfirmationMode='task'|'event'|'acknowledge'|'';

export function confirmationMode(notice:Notice):ConfirmationMode{
  if(['task','event','acknowledge',''].includes(notice.suggested_mode??'missing'))return notice.suggested_mode as ConfirmationMode;
  if(notice.operation==='cancel')return 'acknowledge';
  if(notice.current_task)return 'task';
  const entry=notice.extraction?.entry_type;
  if(entry==='event'||['course','course_change','exam','meeting'].includes(notice.category??''))return 'event';
  if(entry==='notice')return 'acknowledge';
  if(entry==='task'||notice.deadline)return 'task';
  if(notice.extraction?.start||notice.extraction?.end)return 'event';
  if(['assignment','report','registration'].includes(notice.category??''))return 'task';
  return '';
}

export function notificationTime(notice:Notice):string{
  const stamp=(value?:string|null)=>value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'待核对';
  const mode=confirmationMode(notice);
  if(mode==='event')return (notice.category==='course'||notice.category==='course_change'?'上课时间：':'日程时间：')+stamp(notice.extraction?.start)+' — '+stamp(notice.extraction?.end);
  if(mode==='task')return '截止：'+stamp(notice.deadline);
  return mode==='acknowledge'?'通知事项 · 可确认已读':'加入方式与时间待核对';
}
