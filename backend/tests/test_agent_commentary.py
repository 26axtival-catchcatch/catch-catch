"""Only public prose becomes conversation content; execution remains independently replayable."""
import json

import pytest
from langchain_core.messages import AIMessage

from customer_signal.investigation.commentary import public_model_text


@pytest.mark.parametrize('content', [
    '  로밍 검색 이후의 행동을 먼저 확인하겠습니다.  ',
    [{'type': 'text', 'text': '로밍 검색 이후의 행동을 먼저 확인하겠습니다.'}],
])
def test_extracts_regular_provider_text(content):
    assert public_model_text(content) == '로밍 검색 이후의 행동을 먼저 확인하겠습니다.'


def test_only_text_blocks_and_no_private_reasoning_or_tool_arguments():
    content = [
        {'type': 'thinking', 'thinking': 'private-thinking-marker'},
        {'type': 'reasoning', 'text': 'private-reasoning-marker'},
        {'type': 'text', 'text': 'private-thought-marker', 'thought': True},
        {'type': 'tool_use', 'input': {'sql': 'private-sql-marker'}},
        {'type': 'text', 'text': '두 고객 그룹의 차이를 확인하겠습니다.'},
        {'type': 'text', 'text': '확인한 근거를 정리하겠습니다.'},
    ]
    assert public_model_text(content) == '두 고객 그룹의 차이를 확인하겠습니다.\n\n확인한 근거를 정리하겠습니다.'
    assert public_model_text([{'type': 'reasoning', 'text': 'private'}]) is None
    assert public_model_text('  ') is None
    assert public_model_text({'text': 'untyped provider object'}) is None


def test_public_text_is_bounded_and_masks_contact_identifiers():
    text = public_model_text('user@example.com 010-1234-5678 customer_abc123 의 기록을 확인합니다.')
    assert 'user@example.com' not in text
    assert '010-1234-5678' not in text
    assert 'customer_abc123' not in text
    assert 'customer_abc123' not in public_model_text('customer_abc123가 조건에 포함됩니다.')
    assert len(public_model_text('긴 문장입니다. ' * 300)) <= 1000
    assert public_model_text('<think>private</think>') is None
    assert public_model_text('{"secret": "private"}') is None
    assert public_model_text('```sql\nSELECT * FROM events\n```') is None


async def test_model_commentary_emits_before_tools_and_replays_with_role_identity():
    from customer_signal.investigation.activity import ActivityStream
    from customer_signal.investigation.contracts import Narrative
    from customer_signal.investigation.model import GeminiInvestigationModel
    from customer_signal.runtime.events import validate_generic_event
    from customer_signal.packs.customer_signal import _emission_for
    from customer_signal.runtime.wire_projection import wire_events_for
    from test_investigation_model import ScriptedProvider, Data, finish
    from test_journal_wire_replay import canonical

    events = []
    async def emit(event):
        events.append(event)

    class CheckedData(Data):
        def query(self, sql):
            assert any(e.payload.get('message_kind') == 'commentary' for e in events)
            return super().query(sql)

    response = AIMessage(content=[
        {'type': 'thinking', 'thinking': 'private-reasoning'},
        {'type': 'text', 'text': '상담으로 이어진 고객 수를 확인하겠습니다.'},
    ], tool_calls=[{'name': 'query_data', 'args': {'sql': 'SELECT 1'}, 'id': 'call-1'}])
    provider = ScriptedProvider({'primary': [response, finish()]})
    stream = ActivityStream(emit)
    node = await stream.agent('investigator', 'task-comments', 2, [])
    model = GeminiInvestigationModel(api_key='test', primary_model='primary', fallback_model='primary', model_factory=provider)
    with stream.bind(node):
        await model.run_role(role='investigator', task_id=node.task_id, instruction='', context={}, data=CheckedData(), result_type=Narrative, round_index=2)
    comments = [e for e in events if e.payload.get('message_kind') == 'commentary']
    assert len(comments) == 1
    payload = comments[0].payload
    assert payload['display_text'] == '모델 응답 생성'
    assert payload['message_text'] == '상담으로 이어진 고객 수를 확인하겠습니다.'
    assert payload['parent_node_id'] == node.node_id
    assert payload['status'] == 'completed' and payload['kind'] == 'model'
    assert payload['task_id'] == node.task_id and payload['round_index'] == 2
    assert all(e.payload.get('message_text') is None for e in events if e.payload['status'] == 'started')
    assert 'private-reasoning' not in json.dumps([e.payload for e in events])
    for event in events:
        parsed = validate_generic_event(event.type, event.payload)
        emission = _emission_for(event)
        assert wire_events_for(canonical('activity.changed', emission.payload)) == [(event.type, parsed)]
