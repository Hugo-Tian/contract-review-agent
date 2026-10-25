import asyncio
import io
import json
from pathlib import Path
import pytest
import pymupdf
from PIL import Image, ImageDraw, ImageFont
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.main import app
from app import store, history, legal, contract_tools
from app.schemas import Document, Block
from app.tool_schemas import RefundRequest, PromiseRequest
from app.parsing import parse_file


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('HISTORY_DB', str(tmp_path / 'history.sqlite3'))
    return TestClient(app)


def document(text='服务费9800元。提供简历修改2次。不保证录用。'):
    import uuid
    identifier = uuid.uuid4().hex
    return Document(id=identifier, name='虚构测试合同', kind='text', blocks=[Block(id=identifier+'b', location='第1段', text=text, source='paste')], coverage='仅测试文本')


def test_refund_decimal_and_over_deduction():
    body = RefundRequest(paid='1000', already_refunded='100', services=[{'name':'辅导','quantity':'3','unit_price':'33.33','basis':'用户核对记录'}],penalty_base='1000',penalty_rate='20',penalty_basis='合同第5条',confirmed=True)
    result = contract_tools.refund(body)
    assert result['scenarios'][0]['estimated_refund'] == '800.01'
    assert result['scenarios'][1]['estimated_refund'] == '600.01'
    body = body.model_copy(update={'paid':body.paid/100})
    result = contract_tools.refund(body)
    assert result['scenarios'][1]['estimated_refund'] == '0.00'
    assert result['scenarios'][1]['excess_deductions'] == '389.99'


@pytest.mark.parametrize('data', [
    {'paid':'NaN','confirmed':True}, {'paid':'-1','confirmed':True},
    {'paid':'10.001','confirmed':True}, {'paid':'1','already_refunded':'2','confirmed':True},
    {'paid':'100','penalty_base':'100','penalty_rate':'20','confirmed':True},
    {'paid':'100','confirmed':False}, {'paid':'100','penalty_rate':'101','confirmed':True},
])
def test_refund_rejects_unsafe_inputs(data):
    with pytest.raises(ValidationError):
        RefundRequest(**data)


def test_version_diff_keeps_numeric_changes():
    left, right = document('服务费9800元。提供辅导2次。'), document('服务费9800元。提供辅导4次。新增退款期限7天。')
    result = contract_tools.compare_versions(left, right)
    assert len(result['changes']) == 1
    assert '2次' in result['changes'][0]['before'][0]['text']
    assert '4次' in result['changes'][0]['after'][0]['text']
    assert contract_tools.compare_versions(left, document('服务费9800 元。提供辅导\n2次。'))['changes'] == []


def test_history_restores_report_after_memory_deleted(client):
    doc = document(); store.put(doc)
    result = client.post('/api/analyze', json={'document_id':doc.id,'version':1,'mode':'demo'}).json()
    calc = client.post(f'/api/tools/refund?document_id={doc.id}&version=1',json={'paid':'100','confirmed':True})
    assert calc.status_code == 200
    saved = client.post('/api/history',json={'document_id':doc.id,'version':1,'report_id':result['report_id']})
    assert saved.status_code == 200
    identifier = saved.json()['id']
    store.delete(doc.id)
    restored = client.post('/api/history/'+identifier+'/restore').json()
    assert restored['document']['id'] != doc.id
    assert restored['result']['report'] == result['report']
    assert restored['tools']['refund']['scenarios'][0]['estimated_refund'] == '100.00'
    assert store.get(restored['document']['id'])
    assert client.get('/api/history/'+identifier).json()['document']['id'] == doc.id
    assert client.delete('/api/history/'+identifier).status_code == 204
    assert client.get('/api/history/'+identifier).status_code == 404


def test_history_rejects_mismatched_report_and_preserves_versions(client):
    a,b = document(),document(); store.put(a);store.put(b)
    result=client.post('/api/analyze',json={'document_id':a.id,'version':1,'mode':'demo'}).json()
    assert client.post('/api/history',json={'document_id':b.id,'version':1,'report_id':result['report_id']}).status_code==409
    revised=client.patch('/api/documents/'+a.id,json={'version':1,'edits':{a.blocks[0].id:'服务费9900元。'}})
    assert revised.status_code==200
    assert store.get_version(a.id,1).blocks[0].text==a.blocks[0].text
    assert client.get('/api/documents/'+a.id+'/versions').json()==[1,2]
    assert client.post('/api/history',json={'document_id':a.id,'version':2,'report_id':result['report_id']}).status_code==409
    assert client.post('/api/tools/compare',json={'left':{'document_id':a.id,'version':1},'right':{'document_id':a.id,'version':2}}).json()['changes']


def test_official_corpus_complete_and_searchable():
    corpus=legal.load()
    assert len(corpus['articles']) == sum(len(s['articles']) for s in legal.SOURCES)
    for row in corpus['articles']:
        assert row['url'].startswith('https://')
        assert not any(token in row['text'] for token in ('L100:', '责任编辑', '网站地图'))
    result=legal.search('退款')
    assert result['results'] and any('返还' in row['text'] or '退还' in row['text'] for row in result['results'])
    item=next(a for a in corpus['articles'] if a['id']=='prepaid:第十四条')
    assert '七日' in item['text'] and '除外' in item['text']  # Preserve exception, not just headline.
    assert '不适用' not in item['text'] or len(item['text'])>50


def test_legal_refresh_failure_preserves_cache(tmp_path,monkeypatch):
    target=tmp_path/'laws.json';target.write_text(json.dumps(legal.load(),ensure_ascii=False),encoding='utf-8')
    monkeypatch.setattr(legal,'CORPUS',target)
    async def broken(*args,**kwargs):
        import httpx
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(legal.httpx.AsyncClient,'get',broken)
    result=asyncio.run(legal.refresh())
    assert result['count']==46
    assert all(source['error'] for source in result['sources'])


def test_ocr_image_and_scanned_pdf_real_engine():
    font_path=Path('C:/Windows/Fonts/msyh.ttc')
    if not font_path.exists(): pytest.skip('Windows Chinese font unavailable')
    image=Image.new('RGB',(1100,400),'white');draw=ImageDraw.Draw(image)
    font=ImageFont.truetype(str(font_path),40)
    draw.text((35,70),'合同金额 9800 元',font=font,fill='black')
    draw.text((35,160),'不保证录用，退款需书面申请。',font=font,fill='black')
    buf=io.BytesIO();image.save(buf,format='PNG');data=buf.getvalue()
    doc=parse_file(data,'test.png')
    assert doc.blocks[0].source=='ocr'
    assert '9800' in doc.blocks[0].text and '不保证' in doc.blocks[0].text
    pdf=pymupdf.open();page=pdf.new_page(width=550,height=200);page.insert_image(page.rect,stream=data)
    doc=parse_file(pdf.tobytes(),'scan.pdf')
    assert doc.blocks[0].source=='ocr' and '9800' in doc.blocks[0].text


def test_promise_rejects_invented_evidence(monkeypatch):
    doc=document();request=PromiseRequest(document_id=doc.id,version=1,promises='保证录用',consent=True)
    monkeypatch.setenv('MODEL_NAME','test');monkeypatch.setenv('MODEL_API_KEY','test-key')
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'items':[{'promise_id':1,'status':'说法不一致','explanation':'不同','question':'请确认','evidence':[{'block_id':doc.blocks[0].id,'quote_id':'invented'}]}]})}}]}
    async def response(*args,**kwargs):return Response()
    monkeypatch.setattr(contract_tools.httpx.AsyncClient,'post',response)
    with pytest.raises(contract_tools.ModelFailure):asyncio.run(contract_tools.compare_promises(doc,request))


def test_promise_requires_consent(client):
    doc=document();store.put(doc)
    assert client.post('/api/tools/promises',json={'document_id':doc.id,'version':1,'promises':'保证录用','consent':False}).status_code==400
