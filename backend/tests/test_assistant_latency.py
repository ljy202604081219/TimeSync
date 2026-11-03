"""Prompt compaction keeps conversation semantics and inherited memory."""
import asyncio
import json
from app import assistant
from app.models import AssistantThread,User


def test_compaction_retains_all_utterances_timestamps_and_applied_events():
    history=[{'role':'assistant','content':'已保存：高数复习','created_at':'2026-11-03T09:00:00+08:00',
              'event':'applied','answer_source':'model','response_notice':'old-ui-only','response_error':'timeout','mode':'live'},
             {'role':'user','content':'改到明天晚上吧','created_at':'2026-11-03T09:01:00+08:00'}]
    compact=assistant.conversation_history(history)
    assert len(compact)==len(history)
    assert compact[0]=={k:history[0][k] for k in ('role','content','created_at','event')}
    assert compact[1]==history[1]
    assert 'response_error' in history[0]  # Stored history remains unchanged.


def test_omitted_memory_inherits_preferences_in_both_prompt_and_saved_context(system,monkeypatch):
    monkeypatch.setenv('AI_API_KEY','test-only');monkeypatch.setenv('ASSISTANT_MODE','auto')
    monkeypatch.setenv('AI_BUDGET_ENABLED','false')
    seen=[]
    async def model(_system,content):
        data=json.loads(content);seen.append(data)
        if 'trusted_facts' not in data:return {'intent':'help'}  # No new preference this turn.
        assert data['understanding']['memory']=='用户偏好晚上八点后学习'
        assert 'response_error' not in str(data['history'])
        return {'answer':'进入多人协调，选择候选时间并邀请成员确认。'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    with system[1]() as db:
        ident='9235bc6b-5401-4b15-bbfb-778393e390c2'
        db.add(AssistantThread(id=ident,owner_id='A',revision=0,updated_at=assistant.now(),
            messages=[{'role':'user','content':'我喜欢晚上八点后学习','created_at':assistant.now()},
                      {'role':'assistant','content':'好的','answer_source':'model','response_error':None}],
            context={'memory':'用户偏好晚上八点后学习'}));db.commit()
        result=asyncio.run(assistant.chat(db,db.get(User,'A'),assistant.ChatInput(message='怎么创建多人会议？',conversation_id=ident)))
        assert result['answer_source']=='model'
        saved=db.get(AssistantThread,ident)
        assert saved.context['memory']=='用户偏好晚上八点后学习'
        assert seen[0]['previous_context']['memory']==saved.context['memory']
        assert len(seen[0]['recent_history'])==2 and len(seen[1]['history'])==2
