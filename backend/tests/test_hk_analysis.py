"""Hong Kong edition, stage ③: prompt, output language, citations in English/Traditional text, redaction."""
import asyncio
import json
import uuid
import pytest
from pydantic import ValidationError
from app import analysis
from app.profiles import hk, cn
from app.schemas import Context, Document, Block, Report, Fact, Issue, Evidence

ENGLISH = ('1. Landlord: Harbour Example Ltd. Tenant: Wong Siu Ming. Premises: Flat X, Example Mansion, Hong Kong. '
           '2. The first 12 months are fixed. Rent HK$12,000.50 is payable on 1 Dec. 2026 and monthly thereafter; see cl. 5.2. '
           '3. The Tenant shall be responsible for all repairs.')
TRADITIONAL = '第二條 租金每月港幣12,000元，於每月1日繳付。第三條 按金港幣24,000元，退租交吉後退還；退還期限另行通知。'


@pytest.fixture(autouse=True)
def hong_kong(monkeypatch):
    monkeypatch.setenv('REGION', 'hk')


def document(*texts):
    identifier = uuid.uuid4().hex
    return Document(id=identifier, name='虚构租约', kind='text', coverage='仅测试文本',
                    blocks=[Block(id=f'{identifier}-b{i}', location=f'第{i}段', text=t, source='paste') for i, t in enumerate(texts, 1)])


# --- redaction -------------------------------------------------------------

@pytest.mark.parametrize('source,secret,label', [
    ('HKID A123456(7)', 'A123456', '香港身份证'),
    ('身份證號碼：AB 123456 (A)', '123456', '香港身份证'),
    ('Tenant HKID No. A1234567 signed', 'A1234567', '香港身份证'),
    ('Passport No. E12345678', 'E12345678', '护照号码'),
    ('護照號碼：K98765432', 'K98765432', '护照号码'),
    ('Tel: 2345 6789', '2345 6789', '香港电话'),
    ('call +852 9123-4567 now', '9123-4567', '香港电话'),
    ('(852) 6123 4567', '6123 4567', '香港电话'),
    ('WhatsApp 91234567', '91234567', '香港电话'),
    ('A/C No.: 012-345678-001', '345678', '银行账号'),
    ('pay into 024-123456-789 monthly', '123456', '银行账号'),
    ('银行户口 123 456 789 012', '789', '银行账号'),
    ('card 4111 1111 1111 1111', '4111', '卡号'),
    ('Landlord: Chan Tai Man', 'Chan Tai Man', '姓名'),
    ('Payee: Mr. Lee Ka Fai', 'Lee Ka Fai', '姓名'),
    ('Name: Mary O\'Brien-Ho', "O'Brien", '姓名'),
    ('收款人：陳大文', '陳大文', '姓名'),
])
def test_hk_redaction_masks(source, secret, label):
    masked = hk.redact(source)
    assert secret not in masked and label in masked


@pytest.mark.parametrize('text', [
    'Monthly rent HK$12,000.50; deposit HK$24,000.00.',
    'Total HK$24000000 payable on 20261201.',          # 8 digits that are an amount and a date
    'Reference 51234567 and invoice 98765432.',        # bare 8-digit numbers are not treated as phones
    'Room 2301-2305, 12/F, Fictional Road.',          # address ranges are kept
    'Clause 5.2.1 applies from 1/12/2026 to 30/11/2028.',
    'Card-like 1234 5678 9012 3456 fails the checksum.',
    'Landlord: Harbour Example Ltd.',                  # company names are not personal data
    'Tenant: The Tenant shall pay the rent.',
    'Premises: Flat X, Example Mansion, 8 Fictional Road, Hong Kong.',  # addresses kept, user is warned
])
def test_hk_redaction_keeps_amounts_dates_addresses_and_companies(text):
    assert hk.redact(text) == text


def test_hk_pseudonyms_keep_payee_landlord_comparison_and_mainland_rules():
    masked = hk.redact('Landlord: Chan Tai Man. Payee: Mr. Chan Tai Man. Agent: Lee Ka Fai.')
    tokens = [part.split('已脱敏')[0] for part in masked.split('[姓名·')[1:]]
    assert tokens[0] == tokens[1] != tokens[2]  # Same person, same token; another person differs.
    assert 'Chan' not in masked and 'Lee' not in masked
    assert analysis.redact('邮箱 a.b@example.com 手机13812345678') == '邮箱 [邮箱已脱敏] 手机[手机号已脱敏]'


def test_outbound_preview_uses_hk_rules_and_warns_about_addresses(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        doc = client.post('/api/documents/text', json={'text': 'Tenant: Wong Siu Ming, HKID A123456(7). Premises: Flat X, Example Mansion.'}).json()
        outbound = client.get(f"/api/documents/{doc['id']}/outbound").json()
        assert 'Wong' not in outbound['blocks'][0]['text'] and 'Example Mansion' in outbound['blocks'][0]['text']
        assert '地址' in client.get('/api/profile').json()['ui']['outbound_warning']


# --- sentence splitting and citation backfill ------------------------------

@pytest.mark.parametrize('text', [ENGLISH, TRADITIONAL, ENGLISH + '\n' + TRADITIONAL, 'No full stop at all', '  leading. \n\nTrailing!  '])
def test_split_keeps_every_character(text):
    assert ''.join(hk.split_sentences(text)) == text


def test_split_respects_abbreviations_and_list_markers():
    pieces = hk.split_sentences(ENGLISH)
    assert any(p.startswith('1. Landlord: Harbour Example Ltd. Tenant') for p in pieces)
    assert any('1 Dec. 2026 and monthly thereafter; ' in p for p in pieces)
    assert any('HK$12,000.50' in p for p in pieces)
    assert '第二條 租金每月港幣12,000元，於每月1日繳付。' in hk.split_sentences(TRADITIONAL)


def model_report(**overrides):
    data = {'summary': 'Check the fixed term and repairs.', 'questions': ['Q1?', 'Q2?', 'Q3?'], 'amendments': [], 'message': 'Hi',
            'facts': [{'label': label, 'value': '未发现明确约定', 'evidence': []} for label in hk.FACT_LABELS], 'issues': []}
    data.update(overrides)
    return data


def mock_model(monkeypatch, replies):
    calls = []

    class Response:
        status_code = 200
        def __init__(self, content): self.content = content
        def json(self): return {'choices': [{'finish_reason': 'stop', 'message': {'content': self.content}}]}

    class MockClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            calls.append(kwargs['json'])
            return Response(json.dumps(replies[min(len(calls), len(replies)) - 1], ensure_ascii=False))

    monkeypatch.setattr(analysis.httpx, 'AsyncClient', MockClient)
    monkeypatch.setenv('MODEL_API_KEY', 'test'); monkeypatch.setenv('MODEL_NAME', 'test')
    return calls


def find(blocks, block_index, needle):
    block = blocks[block_index]
    return {'block_id': block['id'], 'quote_id': next(p['quote_id'] for p in block['passages'] if needle in p['text'])}


def test_english_and_traditional_quotes_backfilled_verbatim(monkeypatch):
    doc = document(ENGLISH, TRADITIONAL)
    blocks, _ = analysis.evidence_catalog(analysis.masked_document(doc))
    facts = [{'label': label, 'value': '未发现明确约定', 'evidence': []} for label in hk.FACT_LABELS]
    facts[4] = {'label': '租金与付款', 'value': 'HK$12,000.50 a month', 'evidence': [find(blocks, 0, 'HK$12,000.50'), find(blocks, 1, '第二條')]}
    issue = {'title': 'Repairs all on you', 'level': '高', 'reason': 'r', 'explanation': 'e', 'impact': 'i', 'status': '明确约定',
             'question': 'Can minor repairs be listed?', 'negotiation': 'n', 'evidence': [find(blocks, 0, 'all repairs')]}
    calls = mock_model(monkeypatch, [model_report(facts=facts, issues=[issue])])
    report = asyncio.run(analysis.analyze(doc, Context(output_language='English', channel='电邮', recipient='代理')))
    quotes = [e.quote for e in report.facts[4].evidence]
    assert quotes[0] == 'Rent HK$12,000.50 is payable on 1 Dec. 2026 and monthly thereafter; ' and quotes[0] in ENGLISH
    assert quotes[1] == '第二條 租金每月港幣12,000元，於每月1日繳付。'
    assert report.issues[0].evidence[0].quote == '3. The Tenant shall be responsible for all repairs.'
    payload = json.loads(calls[0]['messages'][1]['content'])
    assert calls[0]['messages'][0]['content'] == hk.SYSTEM
    assert payload['context']['output_language'] == 'English' and payload['context']['channel'] == '电邮' and payload['context']['recipient'] == '代理'
    assert payload['required_facts'] == list(hk.FACT_LABELS)
    assert 'Wong Siu Ming' not in calls[0]['messages'][1]['content']


@pytest.mark.parametrize('claim', [
    '这是骗局，请勿付款。', '業主是假的。', 'This is a scam.', '扣按金的做法不合法。', 'Deposit deduction is illegal here.',
    '根据 Cap. 7 处理。', 'See section 13E of the Landlord and Tenant (Consolidation) Ordinance.', '依《印花稅條例》第4條。',
    '詳見 https://example.com',
])
def test_hk_report_rejects_fraud_identity_legality_and_citations(claim):
    doc = document(ENGLISH)
    report = Report.model_validate(model_report(summary='ok'))
    report.issues = [Issue(title='t', level='中', reason='r', explanation=claim, impact='i', status='信息缺失', question='q', negotiation='n', evidence=[])]
    with pytest.raises(analysis.ReportCheckError, match='外部来源'):
        analysis.validate_evidence(report, doc)


@pytest.mark.parametrize('ok', ['Section 5 of your lease says repairs are on you.', '收款人与租约写明的出租人不同，建议到土地注册处查册核实。', '合约没写按金扣减标准。'])
def test_hk_report_allows_lease_clauses_and_neutral_findings(ok):
    report = Report.model_validate(model_report())
    report.issues = [Issue(title='t', level='中', reason='r', explanation=ok, impact='i', status='信息缺失', question='q', negotiation='n', evidence=[])]
    analysis.validate_evidence(report, document(ENGLISH))


def test_hk_fact_set_is_enforced(monkeypatch):
    mock_model(monkeypatch, [model_report(facts=[{'label': label, 'value': '未发现明确约定', 'evidence': []} for label in cn.FACT_LABELS])])
    with pytest.raises(analysis.ModelFailure, match='事实字段'):
        asyncio.run(analysis.analyze(document(ENGLISH), Context()))


# --- output language and channel options ------------------------------------

def test_output_language_channel_and_recipient_options(monkeypatch):
    context = Context()
    assert (context.output_language, context.channel, context.recipient) == ('简体中文', 'WhatsApp', '业主')
    for value in ('繁體中文', 'English'):
        assert Context(output_language=value).output_language == value
    for bad in ({'output_language': '日本語'}, {'channel': 'Telegram'}, {'recipient': '二房东'}):
        with pytest.raises(ValidationError):
            Context(**bad)
    monkeypatch.setenv('REGION', 'cn')
    assert 'output_language' not in Context().for_model()
    with pytest.raises(ValidationError):
        Context(output_language='English')


def test_hk_prompt_keeps_reliability_rules():
    for rule in ('不可信数据', 'block_id 和 quote_id', '不要输出quote或location', '确定的法律效力', '无问题不凑数量', '当前覆盖范围内未发现',
                 '不做诈骗判断', '不判断按金扣减或任何收费是否合法', '土地注册处查册', 'context.output_language', '未发现明确约定', '差饷', '交吉', '细订'):
        assert rule in hk.SYSTEM, rule
