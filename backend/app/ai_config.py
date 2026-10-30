"""Local-only MiMo configuration. Secrets never enter DB request records."""
import os
import json
import tempfile
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit
from dotenv import set_key
from pydantic import BaseModel, SecretStr, Field
import httpx

ENV_FILE=Path(__file__).resolve().parents[2]/'.env'
LOCK=RLock()
BASE='https://api.xiaomimimo.com/v1'
MODEL='mimo-v2.6-pro'

class SettingsInput(BaseModel):
    model_config={'extra':'forbid'}
    base_url: str = Field(default=BASE,max_length=250)
    model: str = Field(default=MODEL,min_length=1,max_length=100,pattern=r'^[a-zA-Z0-9._/-]+$')
    api_key: SecretStr = SecretStr('')

def status():
    return {'provider':os.getenv('AI_PROVIDER','openai-compatible'),'base_url':os.getenv('AI_BASE_URL',BASE),'model':os.getenv('AI_MODEL',MODEL),'has_key':bool(os.getenv('AI_API_KEY')),'mode':'live' if os.getenv('AI_API_KEY') else 'demo'}

def resolved(data):
    base=data.base_url.strip().rstrip('/')
    parsed=urlsplit(base)
    if parsed.scheme!='https' or not parsed.hostname or not (parsed.hostname=='api.xiaomimimo.com' or parsed.hostname.endswith('.xiaomimimo.com')) or parsed.username or parsed.password or parsed.port not in (None,443) or parsed.path!='/v1' or parsed.query or parsed.fragment:
        raise ValueError('请输入 MiMo 官方 HTTPS Base URL，以 /v1 结尾；不要填写 /chat/completions。')
    key=data.api_key.get_secret_value().strip()
    if not key:
        if os.getenv('AI_BASE_URL','').rstrip('/')!=base:
            raise ValueError('切换服务地址时必须重新填写对应的 Key。')
        key=os.getenv('AI_API_KEY','')
    if not key or len(key)>4096 or any(c.isspace() or ord(c)<32 for c in key):
        raise ValueError('请填写有效 API Key，不能包含空格或换行。')
    if not data.model.startswith('mimo-'):
        raise ValueError('请输入 MiMo 模型名称，例如 mimo-v2.6-pro。')
    return {'AI_PROVIDER':'mimo','AI_BASE_URL':base,'AI_MODEL':data.model,'AI_API_KEY':key}

def save(values):
    with LOCK:
        ENV_FILE.parent.mkdir(parents=True,exist_ok=True)
        descriptor,name=tempfile.mkstemp(prefix='.ai-settings-',dir=ENV_FILE.parent)
        os.close(descriptor)
        temporary=Path(name)
        try:
            temporary.write_text(ENV_FILE.read_text(encoding='utf8') if ENV_FILE.exists() else '',encoding='utf8')
            for key,value in values.items(): set_key(str(temporary),key,value)
            os.replace(temporary,ENV_FILE)
            os.environ.update(values)
        finally:
            temporary.unlink(missing_ok=True)

def explain(error):
    if isinstance(error,httpx.HTTPStatusError):
        code=error.response.status_code
        return {401:'Key 无效或与服务地址不匹配（401）。',403:'账号或模型无访问权限（403）。',404:'模型或接口不存在（404），请核对模型名与 Base URL。',402:'账号余额或额度不足（402）。',429:'请求频率或额度受限（429），请检查 MiMo 控制台。'}.get(code,f'MiMo 服务返回 HTTP {code}，请稍后重试。')
    if isinstance(error,httpx.TimeoutException): return 'MiMo 请求超时，请稍后重试。'
    if isinstance(error,httpx.RequestError): return '无法连接 MiMo，请检查网络与服务地址。'
    return '模型返回的 JSON 不完整或字段不符合要求；没有保存识别结果。'

async def test_and_save(data):
    values=resolved(data)
    # Synthetic, non-personal input; validates auth, model invocation AND JSON mode.
    async with httpx.AsyncClient(timeout=45) as client:
        response=await client.post(values['AI_BASE_URL']+'/chat/completions',headers={'api-key':values['AI_API_KEY']},json={'model':values['AI_MODEL'],'messages':[{'role':'system','content':'Return only JSON: {"ok":true}.'},{'role':'user','content':'Connection test. Return {"ok":true}.'}],'response_format':{'type':'json_object'},'thinking':{'type':'disabled'},'max_completion_tokens':256})
        response.raise_for_status()
        output=json.loads(response.json()['choices'][0]['message']['content'])
        if output.get('ok') is not True: raise ValueError('连接测试未返回预期 JSON，配置尚未保存。')
    save(values)
    return {**status(),'tested':True,'notice':'文本与 JSON 调用测试成功，配置已生效。截图能力请在 DDL 页面用实际图片另行验证。'}
