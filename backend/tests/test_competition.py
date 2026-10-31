from fastapi.testclient import TestClient
from app import main, store
from app.analysis import demo_report


def setup_request(client, **kwargs):
    doc = client.post('/api/documents/text', json={'text': '合同总价9800元。退款按已用服务扣费。'}).json()
    return dict(document_id=doc['id'], version=doc['version'], mode='demo', confirmed=True, **kwargs)


def test_confirmation_and_version_guards():
    with TestClient(main.app) as client:
        body = setup_request(client)
        body['confirmed'] = False
        assert client.post('/api/workflow', json=body).status_code == 400
        body.update(confirmed=True, version=99)
        assert client.post('/api/workflow', json=body).status_code == 409


def test_demo_never_calls_model(monkeypatch):
    async def forbidden(*args):
        raise AssertionError('demo must not use model')
    monkeypatch.setattr(main, 'analyze', forbidden)
    with TestClient(main.app) as client:
        body = setup_request(client, promises='保证就业')
        response = client.post('/api/workflow', json=body)
        assert response.status_code == 200
        result = response.json()
        assert result['workflow']['engine'] == 'openJiuwen'
        assert result['workflow']['sdk_version'] == '0.1.18'
        assert result['workflow']['nodes'] == ['confirm', 'analyze', 'promises', 'legal', 'finalize']
        assert result['workflow']['references'] == []
        assert result['workflow']['trace'][2]['status'] == '跳过'
        assert store.get_report(result['report_id'])['result']['workflow'] == result['workflow']


def test_live_partial_failure_keeps_report(monkeypatch):
    async def analyze(doc, context):
        return demo_report(doc)
    async def broken(body):
        raise main.HTTPException(502, '承诺引用校验失败')
    monkeypatch.setattr(main, 'configured', lambda: True)
    monkeypatch.setattr(main, 'analyze', analyze)
    monkeypatch.setattr(main, 'promises', broken)
    with TestClient(main.app) as client:
        body = setup_request(client, promises='保证就业', consent=True)
        body['mode'] = 'live'
        response = client.post('/api/workflow', json=body)
        assert response.status_code == 200
        result = response.json()
        assert result['workflow']['partial'] is True
        assert result['workflow']['trace'][2]['status'] == '失败'
        assert result['report_id']


def test_live_requires_consent_before_any_model(monkeypatch):
    monkeypatch.setattr(main, 'configured', lambda: True)
    with TestClient(main.app) as client:
        body = setup_request(client)
        body['mode'] = 'live'
        assert client.post('/api/workflow', json=body).status_code == 400


def test_live_success_and_version_change(monkeypatch):
    async def analyze(doc, context):
        return demo_report(doc)
    async def compare(doc, body):
        return {'items': [], 'note': 'test', 'source': body.source}
    monkeypatch.setattr(main, 'configured', lambda: True)
    monkeypatch.setattr(main, 'analyze', analyze)
    monkeypatch.setattr(main.contract_tools, 'compare_promises', compare)
    with TestClient(main.app) as client:
        body = setup_request(client, promises='保证就业', consent=True)
        body['mode'] = 'live'
        result = client.post('/api/workflow', json=body).json()
        assert result['workflow']['trace'][2]['status'] == '完成'
        assert not result['workflow']['partial']
        assert 'promises' in store.get_tools(body['document_id'], body['version'])
        async def change(doc, context):
            new = doc.model_copy(deep=True)
            new.version += 1
            store.put(new)
            return demo_report(doc)
        monkeypatch.setattr(main, 'analyze', change)
        assert client.post('/api/workflow', json=body).status_code == 409


def test_sdk_really_dispatches_nodes_with_status_only(monkeypatch):
    from app import jiuwen_workflow as sdk
    observed = []
    original = sdk.TaskNode.invoke
    async def record(self, inputs, session, context):
        result = await original(self, inputs, session, context)
        observed.append((self.name, inputs, result))
        return result
    monkeypatch.setattr(sdk.TaskNode, 'invoke', record)
    with TestClient(main.app) as client:
        body = setup_request(client, promises='PRIVATE_TEST_PROMISE')
        result = client.post('/api/workflow', json=body)
        assert result.status_code == 200
        assert [entry[0] for entry in observed] == list(sdk.NODE_IDS)
        assert 'PRIVATE_TEST_PROMISE' not in str(observed)
        assert all(entry[2] == {'status': 'completed'} for entry in observed)
