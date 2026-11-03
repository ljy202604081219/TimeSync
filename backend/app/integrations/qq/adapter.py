"""OneBot v11 -> minimal records. No sender identities or outbound messages."""
import base64
import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlsplit
from ...timeutil import TZ
from .vendor import flatten_message

def conversation_key(event):
    if event.message_type=='group':return str(event.group_id) if str(event.group_id) else None
    if event.message_type=='private':
        peer=event.target_id if str(event.user_id)==str(event.self_id) else event.user_id
        return 'private:'+str(peer) if str(peer) and str(peer)!='0' else None
    return None

def normalize(event,include_self=False):
    if event.post_type=='meta_event':return None
    if event.post_type not in ('message','message_sent') or event.message_type not in ('group','private'):return None
    outgoing=str(event.user_id)==str(event.self_id)
    if outgoing and not include_self:return None
    key=conversation_key(event)
    if not str(event.message_id) or not key:raise ValueError('消息必须提供message_id和会话目标')
    segments=event.message or event.raw_message
    if isinstance(segments,str):
        # CQ string input: preserve media markers, never interpret as commands.
        parts=[];cursor=0
        for m in re.finditer(r'\[CQ:([^,\]]+)([^\]]*)\]',segments):
            parts.append({'type':'text','data':{'text':segments[cursor:m.start()]}})
            data=dict(re.findall(r',([^=,]+)=([^,]*)',m[2]))
            parts.append({'type':m[1],'data':data});cursor=m.end()
        parts.append({'type':'text','data':{'text':segments[cursor:]}});segments=parts
    if len(segments)>100:raise ValueError('消息分段过多')
    if any(not isinstance(s,dict) or not isinstance(s.get('data',{}),dict) for s in segments):raise ValueError('消息分段格式无效')
    images=[];files=[]
    for segment in segments:
        if not isinstance(segment,dict):continue
        data=segment.get('data') or {}
        if not isinstance(data,dict):continue
        if segment.get('type')=='image':
            uri=str(data.get('url') or data.get('file') or '')
            if len(uri)>1500000:raise ValueError('单张图片过大')
            images.append(uri)
        if segment.get('type')=='file':
            # Text already extracted by an authorized bridge is accepted as
            # untrusted text. No file path, archive or executable is opened.
            text=str(data.get('text') or '')[:12000]
            files.append('\n附件正文：'+text if text else '\n[附件需手动查看，未自动解析]')
    text=flatten_message(segments) or event.raw_message
    if outgoing:text='【小号发出】\n'+text
    text=re.sub(r'@\d+','@成员',text)+''.join(files)
    text=text[:16000]
    if len(images)>3:raise ValueError('每条消息最多处理3张图片')
    sent_at=datetime.fromtimestamp(event.time,TZ).isoformat(timespec='seconds')
    digest=hashlib.sha256(json.dumps([text,images,sent_at],ensure_ascii=False).encode()).hexdigest()
    return {'message_id':str(event.message_id),'group_id':key,'bot_id':str(event.self_id),
            'sent_at':sent_at,'raw_text':text,'images':images,'content_hash':digest}

def image_content(uri):
    if uri.startswith('base64://'):
        value=uri[9:];binary=base64.b64decode(value,validate=True)
        if len(binary)>1024*1024:raise ValueError('图片超过1MB')
        mime='image/png' if binary.startswith(b'\x89PNG') else 'image/jpeg' if binary.startswith(b'\xff\xd8\xff') else None
        if not mime:raise ValueError('仅支持PNG/JPEG截图')
        return 'data:'+mime+';base64,'+value
    parsed=urlsplit(uri)
    if parsed.scheme=='https' and parsed.hostname in {'gchat.qpic.cn','multimedia.nt.qq.com','gchat.qlogo.cn'} and not parsed.username and not parsed.password:
        return uri
    raise ValueError('图片地址不在QQ媒体白名单，请手动导入截图')
