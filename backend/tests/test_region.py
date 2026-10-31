import asyncio
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app import main, legal, store, analysis, contract_tools
from app.profiles import current, cn, hk, DEFAULT_REGION
from app.schemas import Context, Document, Block
from app.tool_schemas import PromiseRequest


@pytest.fixture
def client():
    with TestClient(main.app) as client:
        yield client


def document(text='Monthly rent HK$12,000.'):
    import uuid
    identifier = uuid.uuid4().hex
    return Document(id=identifier, name='虚构租约', kind='text', blocks=[Block(id=identifier + 'b', location='第1段', text=text, source='paste')], coverage='仅测试文本')


def forbid_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('no network call expected')
    monkeypatch.setattr(analysis.httpx, 'AsyncClient', refuse)
    monkeypatch.setattr(contract_tools.httpx, 'AsyncClient', refuse)
    monkeypatch.setattr(legal.httpx, 'AsyncClient', refuse)


def test_branch_defaults_to_hk_and_rejects_unknown_region(monkeypatch):
    monkeypatch.delenv('REGION')
    assert DEFAULT_REGION == 'hk' and current() is hk.PROFILE
    monkeypatch.setenv('REGION', ' CN ')
    assert current() is cn.PROFILE
    monkeypatch.setenv('REGION', 'tw')
    with pytest.raises(RuntimeError, match='REGION'):
        current()


@pytest.mark.parametrize('region,currency,first_fact', [('cn', 'CNY', '签约主体'), ('hk', 'HKD', '出租人及身份')])
def test_profile_endpoint_switches_and_hides_internals(client, monkeypatch, region, currency, first_fact):
    monkeypatch.setenv('REGION', region)
    body = client.get('/api/profile').json()
    assert body['region'] == region and body['currency']['code'] == currency
    assert body['fact_labels'][0] == first_fact and len(body['fact_labels']) == 10
    assert client.get('/api/health').json()['region'] == region
    text = str(body)
    assert '不可信数据' not in text and 'schema' not in text  # Prompts never leave the backend.


def test_context_options_follow_region(monkeypatch):
    assert Context().model_dump()['role'] == '学员'
    monkeypatch.setenv('REGION', 'hk')
    assert Context().role == '租客' and Context().goal == '签约前检查'
    with pytest.raises(ValidationError):
        Context(role='学员')
    monkeypatch.setenv('REGION', 'cn')
    with pytest.raises(ValidationError):
        Context(role='租客')


def test_hk_demo_and_validation_use_hk_fact_labels(client, monkeypatch):
    monkeypatch.setenv('REGION', 'hk')
    doc = client.post('/api/documents/text', json={'text': 'Monthly rent HK$12,000. 虚构示例。'}).json()
    result = client.post('/api/workflow', json={'document_id': doc['id'], 'version': 1, 'mode': 'demo', 'confirmed': True,
                                                 'context': {'role': '准租客', 'goal': '退租与按金'}})
    assert result.status_code == 200, result.text
    body = result.json()
    assert [f['label'] for f in body['report']['facts']] == list(hk.FACT_LABELS)
    assert body['workflow']['trace'][2]['name'] == '业主/代理承诺核验'
    report = analysis.demo_report(store.get(doc['id']))
    report.facts = report.facts[:-1]
    with pytest.raises(analysis.ReportCheckError, match='facts'):
        analysis.validate_evidence(report, store.get(doc['id']))


def test_hk_promise_tool_refused_until_its_prompt_exists(client, monkeypatch):
    monkeypatch.setenv('REGION', 'hk')
    monkeypatch.setenv('MODEL_API_KEY', 'test'); monkeypatch.setenv('MODEL_NAME', 'test')
    forbid_network(monkeypatch)
    assert current().ready == {'analysis': True, 'promises': False, 'legal': False}
    doc = client.post('/api/documents/text', json={'text': 'Deposit HK$24,000.'}).json()
    promise = client.post('/api/tools/promises', json={'document_id': doc['id'], 'version': 1, 'promises': '家电坏了包修', 'consent': True})
    assert promise.status_code == 503 and '香港版' in promise.json()['detail']
    with pytest.raises(contract_tools.ModelFailure):
        asyncio.run(contract_tools.compare_promises(document(), PromiseRequest(document_id='x', version=1, promises='包修', consent=True)))


def test_hk_legal_library_is_empty_not_mainland(client, monkeypatch, tmp_path):
    monkeypatch.setenv('REGION', 'hk')
    monkeypatch.setattr(legal, 'HK_CORPUS', tmp_path / 'hk.json')
    forbid_network(monkeypatch)
    result = client.get('/api/legal/search?q=退款').json()
    assert result['results'] == [] and result['count'] == 0 and '香港法规库尚未建立' in result['note']
    refreshed = client.post('/api/legal/refresh').json()
    assert refreshed['count'] == 0 and refreshed['error']
    assert not (tmp_path / 'hk.json').exists()
    monkeypatch.setenv('REGION', 'cn')
    assert legal.search('退款')['results']


def test_redaction_and_prompt_follow_region(monkeypatch):
    calls = []

    class Response:
        status_code = 200
        def json(self):
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}

    class MockClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs): calls.append(kwargs['json']); return Response()

    monkeypatch.setattr(analysis.httpx, 'AsyncClient', MockClient)
    monkeypatch.setenv('MODEL_API_KEY', 'test'); monkeypatch.setenv('MODEL_NAME', 'test')
    with pytest.raises(analysis.ModelFailure):
        asyncio.run(analysis.analyze(document(), Context()))
    assert calls[0]['messages'][0]['content'] == cn.SYSTEM
    assert '"required_facts": ["签约主体"' in calls[0]['messages'][1]['content']
    assert analysis.redact('手机13812345678') == '手机[手机号已脱敏]'
