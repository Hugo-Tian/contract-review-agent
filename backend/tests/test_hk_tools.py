"""Hong Kong edition, stage ④: promise comparison, deposit/upfront calculators, lease comparison, checklist."""
import asyncio
import json
import uuid
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app import contract_tools, store
from app.main import app
from app.profiles import hk
from app.schemas import Document, Block
from app.tool_schemas import DepositRequest, UpfrontRequest, PromiseRequest

LEASE = ('1. Landlord: Harbour Example Ltd. (sub-landlord). Tenant: Wong Siu Ming. '
         '2. Monthly rent HK$12,000 payable to the account of Mr. Example Agent. '
         '3. Deposit HK$24,000 refundable after vacant possession is delivered. '
         '4. The Tenant shall be responsible for all repairs.')


@pytest.fixture(autouse=True)
def hong_kong(monkeypatch):
    monkeypatch.setenv('REGION', 'hk')


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


def document(*texts):
    identifier = uuid.uuid4().hex
    return Document(id=identifier, name='虚构租约', kind='text', coverage='仅测试文本',
                    blocks=[Block(id=f'{identifier}-b{i}', location=f'第{i}段', text=t, source='paste') for i, t in enumerate(texts, 1)])


# --- deposit and move-out ---------------------------------------------------

def deposit(**kwargs):
    return contract_tools.deposit(DepositRequest(**{'deposit': '24000', 'confirmed': True, **kwargs}))


def test_deposit_decimal_precision_and_two_scenarios():
    result = deposit(prepaid_rent='0.10', rent_arrears='0.20', deductions=[{'name': '清洁', 'amount': '0.10', 'basis': '租约第8条；收据'}],
                     penalty_type='months_rent', monthly_rent='12000.50', penalty_months='1.5', penalty_basis='租约第5条')
    first, second = result['scenarios']
    assert first['balance'] == '23999.80' and first['penalty'] == '0.00'
    assert second['penalty'] == '18000.75' and second['balance'] == '5999.05'
    assert second['formula'] == 'HKD 24000 + 0.10 − 0.20 − 0.10 − 18000.75 = 5999.05'
    assert result['deductions_total'] == '0.10' and '不判断扣费是否合法' in result['note'] and '不代表你还欠' in result['note']


def test_deposit_over_deduction_is_not_debt_and_forfeit_is_explicit():
    result = deposit(rent_arrears='30000.01', penalty_type='forfeit_deposit', penalty_basis='租约第5条：死约期内退租没收按金')
    first, second = result['scenarios']
    assert first['estimated_return'] == '0.00' and first['excess_deductions'] == '6000.01'
    assert second['penalty'] == '24000.00' and second['excess_deductions'] == '30000.01'
    fixed = deposit(penalty_type='fixed', penalty_amount='999.99', penalty_basis='租约第6条')
    assert fixed['scenarios'][1]['balance'] == '23000.01'


@pytest.mark.parametrize('data', [
    {'deposit': '-1'}, {'deposit': 'NaN'}, {'deposit': '1.001'}, {'deposit': '100000001'},
    {'deposit': '1', 'confirmed': False},
    {'deposit': '1', 'penalty_type': 'fixed', 'penalty_amount': '100'},                       # no basis
    {'deposit': '1', 'penalty_type': 'months_rent', 'penalty_basis': '第5条', 'monthly_rent': '1'},  # no months
    {'deposit': '1', 'penalty_type': 'fixed', 'penalty_basis': '第5条'},                        # no amount
    {'deposit': '1', 'deductions': [{'name': '清洁', 'amount': '10', 'basis': ''}]},
    {'deposit': '1', 'penalty_type': 'market_rate', 'penalty_basis': 'x'},
])
def test_deposit_rejects_unsafe_inputs(data):
    with pytest.raises(ValidationError):
        DepositRequest(**{'confirmed': True, **data})


def test_deposit_api_error_does_not_echo_input(client):
    response = client.post('/api/tools/deposit', json={'deposit': 'SECRET-VALUE', 'confirmed': True})
    assert response.status_code == 422 and '按金试算' in response.json()['detail'] and 'SECRET' not in response.text


def test_deposit_result_saved_with_document(client):
    doc = client.post('/api/documents/text', json={'text': LEASE}).json()
    assert client.post(f"/api/tools/deposit?document_id={doc['id']}&version=1", json={'deposit': '24000', 'confirmed': True}).status_code == 200
    assert store.get_tools(doc['id'], 1)['deposit']['scenarios'][0]['balance'] == '24000.00'


# --- upfront costs ----------------------------------------------------------

def test_upfront_uses_only_user_rates_and_rounds_half_up():
    body = UpfrontRequest(first_rent='12000', deposit='24000', stamp_duty_total='1234.55', stamp_duty_share='50', commission_base='12000',
                          commission_rate='50', others=[{'name': '钥匙押金', 'amount': '100.10', 'basis': '代理报价单'}], basis='租约第2、3条', confirmed=True)
    result = contract_tools.upfront(body)
    amounts = {i['name']: i['amount'] for i in result['items']}
    assert amounts['印花税（你分担的部分）'] == '617.28' and amounts['中介佣金'] == '6000.00'
    assert result['total'] == '42717.38'
    assert result['formula'] == 'HKD 12000.00 + 24000.00 + 617.28 + 6000.00 + 100.10 = 42717.38'
    bare = contract_tools.upfront(UpfrontRequest(first_rent='12000', deposit='24000', stamp_duty_total='1000', commission_base='12000', basis='租约', confirmed=True))
    assert bare['total'] == '36000.00'  # No default share or commission rate is assumed.
    assert '不预设' in bare['note']


@pytest.mark.parametrize('data', [{'stamp_duty_share': '101'}, {'commission_rate': '-1'}, {'basis': ''}, {'confirmed': False}])
def test_upfront_rejects_unsafe_inputs(data):
    with pytest.raises(ValidationError):
        UpfrontRequest(**{'first_rent': '1', 'deposit': '1', 'basis': '租约', 'confirmed': True, **data})


# --- landlord / agent promise comparison -------------------------------------

def mock_promise_model(monkeypatch, content):
    calls = []

    class Response:
        def raise_for_status(self): pass
        def json(self): return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(content, ensure_ascii=False)}}]}

    async def post(self, url, **kwargs):
        calls.append(kwargs['json'])
        return Response()

    monkeypatch.setattr(contract_tools.httpx.AsyncClient, 'post', post)
    monkeypatch.setenv('MODEL_NAME', 'test'); monkeypatch.setenv('MODEL_API_KEY', 'test')
    return calls


def test_hk_promise_uses_lease_prompt_language_and_verbatim_quotes(monkeypatch):
    doc = document(LEASE)
    blocks, _ = contract_tools.evidence_catalog(contract_tools.masked_document(doc))
    quote_id = next(p['quote_id'] for p in blocks[0]['passages'] if 'all repairs' in p['text'])
    calls = mock_promise_model(monkeypatch, {'items': [
        {'promise_id': 1, 'status': '说法不一致', 'explanation': 'The lease puts all repairs on you.', 'question': 'Will you add appliance repairs to the lease?',
         'evidence': [{'block_id': doc.blocks[0].id, 'quote_id': quote_id}]},
        {'promise_id': 2, 'status': '合同没找到', 'explanation': 'Not found in this text.', 'question': 'Can this be written in?', 'evidence': []}]})
    request = PromiseRequest(document_id=doc.id, version=1, promises='家电坏了业主包修\n住满一年可提前一个月通知退租', output_language='English', consent=True)
    result = asyncio.run(contract_tools.compare_promises(doc, request))
    assert calls[0]['messages'][0]['content'] == hk.PROMISE_SYSTEM
    assert json.loads(calls[0]['messages'][1]['content'])['output_language'] == 'English'
    assert result['items'][0]['evidence'][0]['quote'] == '4. The Tenant shall be responsible for all repairs.'
    assert '业主或代理' in result['note']


@pytest.mark.parametrize('explanation', ['This is a scam.', '业主是假的，不要租。', 'Charging this fee is illegal.'])
def test_hk_promise_rejects_fraud_identity_and_legality(monkeypatch, explanation):
    doc = document(LEASE)
    mock_promise_model(monkeypatch, {'items': [{'promise_id': 1, 'status': '需要确认', 'explanation': explanation, 'question': 'q', 'evidence': []}]})
    with pytest.raises(contract_tools.ModelFailure):
        asyncio.run(contract_tools.compare_promises(doc, PromiseRequest(document_id=doc.id, version=1, promises='包修', consent=True)))


# --- temporary vs formal lease ------------------------------------------------

def test_hk_compare_finds_changed_terms_and_keeps_word_spaces():
    temporary = document('Monthly rent HK$12,000. Deposit HK$24,000. The Tenant may terminate after 12 months by giving one month notice.')
    formal = document('Monthly rent HK$12,000.  Deposit HK$36,000.\nThe Tenant may terminate after 12 months by giving two months notice.')
    result = contract_tools.compare_versions(temporary, formal)
    assert [c['kind'] for c in result['changes']] == ['修改']
    before = ' | '.join(p['text'] for p in result['changes'][0]['before'])
    after = ' | '.join(p['text'] for p in result['changes'][0]['after'])
    assert 'Deposit HK$24,000.' in before and 'Deposit HK$36,000.' in after and 'two months notice.' in after
    assert '临时租约' in result['note']
    assert contract_tools.compare_versions(temporary, document('Monthly rent   HK$12,000.\nDeposit HK$24,000. The Tenant may terminate after 12 months by giving one month notice.'))['changes'] == []


# --- pre-signing checklist ----------------------------------------------------

def live_snapshot(doc, facts):
    report_id = uuid.uuid4().hex
    all_facts = [{'label': label, 'value': '未发现明确约定', 'evidence': []} for label in hk.FACT_LABELS]
    for item in all_facts:
        item.update(facts.get(item['label'], {}))
    store.put(doc)
    store.put_report(report_id, {'document': doc.model_dump(mode='json'), 'context': None,
                                 'result': {'mode': 'live', 'report_id': report_id, 'report': {'facts': all_facts}}})
    return report_id


def quote(doc, needle):
    masked = contract_tools.masked_document(doc)
    _, catalog = contract_tools.evidence_catalog(masked)
    return next(e.model_dump() for e in catalog.values() if needle in e.quote)


def test_checklist_cites_lease_or_says_not_found(client):
    doc = document(LEASE)
    report_id = live_snapshot(doc, {
        '出租人及身份': {'value': 'Harbour Example Ltd.，写明为 sub-landlord', 'evidence': [quote(doc, 'Landlord')]},
        '收款主体': {'value': '代理个人账户', 'evidence': [quote(doc, 'payable to')]},
        '按金与退还': {'value': '按金两个月', 'evidence': [{'block_id': doc.blocks[0].id, 'quote': 'INVENTED QUOTE', 'location': '第1段'}]},
    })
    response = client.post('/api/tools/checklist', json={'document_id': doc.id, 'version': 1, 'report_id': report_id})
    assert response.status_code == 200, response.text
    items = {i['title']: i for i in response.json()['items']}
    masked_text = contract_tools.masked_document(doc).blocks[0].text
    for item in items.values():
        assert (item['basis'] == '租约原文') == bool(item['evidence'])
        assert all(e['quote'] in masked_text for e in item['evidence'])
        assert not hk.FORBIDDEN.search(item['title'] + item['why'])
    assert '到土地注册处查册，核对业主资料' in items
    assert len(items['付款前核对收款人']['evidence']) == 2  # Payee and landlord wording side by side; no identity verdict.
    assert '要求出示业主同意分租的书面文件' in items                    # "sub-landlord" appears in the lease.
    assert items['问清租约会不会加盖印花']['evidence'] == []              # No stamp duty wording in this lease.
    assert items['入住时自己拍照记录单位状况']['basis'] == '本次正文未找到'
    assert '问清按金几时退、按什么扣' in items                           # Forged citation is dropped, not shown.
    assert '签约前问清：维修责任' in items
    assert 'checklist' in store.get_tools(doc.id, 1)


def test_checklist_without_sublet_wording_has_no_sublet_item(client):
    doc = document('Landlord: Harbour Example Ltd. Monthly rent HK$12,000. This agreement shall be stamped. Inventory in Schedule 1.')
    report_id = live_snapshot(doc, {})
    items = [i['title'] for i in client.post('/api/tools/checklist', json={'document_id': doc.id, 'version': 1, 'report_id': report_id}).json()['items']]
    assert '要求出示业主同意分租的书面文件' not in items
    assert '确认租约是否加盖印花、费用怎么分' in items and '入住时按清单逐项核对并拍照' in items


def test_checklist_requires_live_report_for_same_version(client):
    doc = client.post('/api/documents/text', json={'text': LEASE}).json()
    demo = client.post('/api/analyze', json={'document_id': doc['id'], 'version': 1, 'mode': 'demo'}).json()
    response = client.post('/api/tools/checklist', json={'document_id': doc['id'], 'version': 1, 'report_id': demo['report_id']})
    assert response.status_code == 400 and '真实分析' in response.json()['detail']
    other = document(LEASE)
    report_id = live_snapshot(other, {})
    assert client.post('/api/tools/checklist', json={'document_id': doc['id'], 'version': 1, 'report_id': report_id}).status_code == 409
