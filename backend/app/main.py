import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import sys
import uuid
from dotenv import load_dotenv
from pydantic import Field
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.exceptions import RequestValidationError
from .schemas import Document, Block, TextInput, Revision, AnalysisRequest
from .tool_schemas import PromiseRequest, RefundRequest, CompareRequest, SaveRequest
from . import history, legal, contract_tools
from . import store
from .jiuwen_workflow import SDK_VERSION, run_contract_workflow
from .analysis import configured, demo_report, analyze, ModelFailure, masked_document
from .parsing import MAX_FILE

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / 'backend' / '.env')
analysis_lock = asyncio.Lock()
parse_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app):
    async def janitor():
        while True:
            await asyncio.sleep(60)
            store.cleanup()
    task = asyncio.create_task(janitor())
    yield
    task.cancel()


app = FastAPI(title='合同阅读助手 · 本地 MVP', lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])


@app.middleware('http')
async def local_only(request: Request, call_next):
    origin = request.headers.get('origin')
    if origin and origin not in {'http://127.0.0.1:8000', 'http://localhost:8000', 'http://127.0.0.1:5173', 'http://localhost:5173'}:
        return JSONResponse({'detail': '仅允许本地工作台访问。'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Never reflect sensitive submitted values or exception input.
    if request.url.path == '/api/tools/refund':
        return JSONResponse({'detail': '请检查退款试算：金额须为非负数且最多两位小数，比例为0至100，已退款不得超过实付。服务名称、扣费依据和确认勾选不能遗漏；计算违约金时还需填写基数和依据。'}, status_code=422)
    return JSONResponse({'detail': '提交的数据格式不正确，请检查输入内容和版本。'}, status_code=422)


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=400)


def require_doc(doc_id: str, version: int | None = None):
    doc = store.get(doc_id)
    if not doc:
        raise HTTPException(404, '临时文档已过期或不存在，请重新上传。')
    if version is not None and doc.version != version:
        raise HTTPException(409, '文档版本已改变，请刷新后重新确认。')
    return doc


@app.get('/api/health')
async def health():
    return {'model_configured': configured(), 'max_analysis_chars': int(os.getenv('MAX_ANALYSIS_CHARS', '24000')),
            'mode': 'single-user-local', 'workflow_engine': 'openJiuwen', 'sdk_version': SDK_VERSION, 'capabilities': {'ocr': True, 'legal_search': True, 'refund': True, 'comparison': True, 'history': True, 'promises': True, 'workflow': True}}


@app.post('/api/documents/text')
async def from_text(body: TextInput):
    paragraphs = [p.strip() for p in body.text.split('\n') if p.strip()]
    if not paragraphs:
        raise HTTPException(400, '没有可分析正文。')
    doc_id = uuid.uuid4().hex
    doc = Document(id=doc_id, name='粘贴的合同', kind='text',
                   blocks=[Block(id=f'{doc_id}-b{i:04}', location=f'粘贴文本段落 {i}', text=p, source='paste') for i, p in enumerate(paragraphs, 1)],
                   coverage=f'粘贴文本共 {len(paragraphs)} 段，仅覆盖提交内容')
    store.put(doc)
    return doc


@app.post('/api/documents/upload')
async def upload(request: Request):
    # Raw stream avoids multipart spooling originals to disk before the size check.
    name = request.query_params.get('name', 'upload')[-200:]
    ocr_mode = request.query_params.get('ocr', 'auto')
    if ocr_mode not in {'auto', 'force', 'off'}:
        raise HTTPException(400, '未知OCR模式。')
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_FILE:
            raise HTTPException(413, '文件超过 10 MB 限制。')
    async with parse_lock:
        process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'app.parsing', name, ocr_mode,
                    cwd=str(ROOT / 'backend'), stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            output, _ = await asyncio.wait_for(process.communicate(bytes(data)), timeout=180)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise HTTPException(408, '解析或OCR超过 180 秒，已停止。请拆分文件后重试。') from None
    try:
        result = json.loads(output)
    except (ValueError, UnicodeError):
        raise HTTPException(400, '文档解析失败，请检查文件是否损坏。') from None
    if process.returncode or 'error' in result:
        raise HTTPException(400, result.get('error', '解析失败。'))
    doc = Document.model_validate(result)
    store.put(doc)
    return doc


@app.patch('/api/documents/{doc_id}')
async def revise(doc_id: str, body: Revision):
    doc = require_doc(doc_id, body.version)
    if set(body.edits) - {b.id for b in doc.blocks}:
        raise HTTPException(400, '修订中包含未知文本块。')
    if any(not text.strip() for text in body.edits.values()):
        raise HTTPException(400, '修订文本不能为空；请保留需核对的内容说明。')
    for block in doc.blocks:
        if block.id in body.edits and body.edits[block.id] != block.text:
            block.original_text = block.original_text if block.original_text is not None else block.text
            block.text = body.edits[block.id].strip()
            block.source = 'user_revision'
            block.status = 'user_corrected'
    if sum(len(b.text) for b in doc.blocks) > 250000:
        raise HTTPException(413, '修订后的正文过长。')
    doc.version += 1
    store.put(doc)
    return doc


@app.delete('/api/documents/{doc_id}', status_code=204)
async def delete(doc_id: str):
    store.delete(doc_id)


@app.get('/api/documents/{doc_id}/outbound')
async def outbound(doc_id: str):
    return masked_document(require_doc(doc_id))


@app.post('/api/analyze')
async def report(body: AnalysisRequest):
    doc = require_doc(body.document_id, body.version)
    if sum(len(b.text) for b in doc.blocks) > int(os.getenv('MAX_ANALYSIS_CHARS', '24000')):
        raise HTTPException(413, '正文超过本阶段单次分析长度上限，未进行截断或分析。长合同分段和跨条款合并尚未实现。')
    if body.mode == 'live':
        if not configured():
            raise HTTPException(503, '未配置真实模型，请在后端 .env 设置地址、密钥及模型。')
        if not body.consent:
            raise HTTPException(400, '请先确认同意将脱敏正文与背景发送给配置的模型服务。')
        if analysis_lock.locked():
            raise HTTPException(409, '已有分析正在处理，请稍后重试。')
        async with analysis_lock:
            try:
                result = await analyze(doc, body.context)
            except ModelFailure as exc:
                raise HTTPException(502, str(exc)) from None
    else:
        result = demo_report(doc)
    report_id = uuid.uuid4().hex
    response = {'mode': body.mode, 'document_id': doc.id, 'version': doc.version, 'report_id': report_id,
            'coverage': doc.coverage, 'warnings': doc.warnings,
            'scope_note': '这里只看了本次提取的文字。“没找到”不代表原文件里一定没有。引用已与原文核对，但解释仍可能有误，请结合完整合同确认。',
            'evidence_status': '演示引用' if body.mode == 'demo' else '引用已核对原文，解释还请你确认',
            'report': result.model_dump(mode='json')}
    store.put_report(report_id, {'document': doc.model_dump(mode='json'), 'context': body.context.model_dump(), 'result': response})
    return response


@app.get('/api/documents/{doc_id}/versions')
async def document_versions(doc_id: str):
    require_doc(doc_id)
    return store.versions(doc_id)


@app.post('/api/tools/promises')
async def promises(body: PromiseRequest):
    doc = require_doc(body.document_id, body.version)
    if not body.consent:
        raise HTTPException(400, '请同意发送脱敏合同与销售说法。')
    if not configured():
        raise HTTPException(503, '未配置真实模型。')
    if sum(len(b.text) for b in doc.blocks) > int(os.getenv('MAX_ANALYSIS_CHARS', '24000')):
        raise HTTPException(413, '合同正文过长，请拆分后对照。')
    if analysis_lock.locked():
        raise HTTPException(409, '已有分析正在处理，请稍后重试。')
    async with analysis_lock:
        try:
            result = await contract_tools.compare_promises(doc, body)
        except ModelFailure as exc:
            raise HTTPException(502, str(exc)) from None
    store.put_tool(doc.id, doc.version, 'promises', result)
    return result


@app.post('/api/tools/refund')
async def refund(body: RefundRequest, document_id: str | None = None, version: int | None = None):
    result = contract_tools.refund(body)
    if document_id:
        doc = require_doc(document_id, version)
        store.put_tool(doc.id, doc.version, 'refund', result)
    return result


def snapshot_document(ref):
    if ref.history_id:
        snapshot = history.get(ref.history_id)
        if not snapshot:
            raise HTTPException(404, '历史记录不存在。')
        return Document.model_validate(snapshot['document'])
    doc = store.get_version(ref.document_id, ref.version)
    if not doc:
        raise HTTPException(404, '临时版本已过期，请从历史记录选择或重新上传。')
    return doc


@app.post('/api/tools/compare')
async def compare(body: CompareRequest):
    left, right = snapshot_document(body.left), snapshot_document(body.right)
    return await asyncio.to_thread(contract_tools.compare_versions, left, right)


@app.get('/api/legal/search')
async def legal_search(q: str = ''):
    if len(q) > 100:
        raise HTTPException(400, '检索词请控制在100字内。')
    return legal.search(q)


@app.post('/api/legal/refresh')
async def legal_refresh():
    if legal.refresh_lock.locked():
        raise HTTPException(409, '法规来源正在更新，请稍后。')
    return await legal.refresh()


@app.post('/api/history')
async def save_history(body: SaveRequest):
    doc = require_doc(body.document_id, body.version)
    if body.report_id:
        snapshot = store.get_report(body.report_id)
        if not snapshot or snapshot['document']['id'] != doc.id or snapshot['document']['version'] != doc.version:
            raise HTTPException(409, '报告与当前文档版本不匹配，请重新生成报告。')
    else:
        snapshot = {'document': doc.model_dump(mode='json'), 'context': None, 'result': None}
    snapshot['tools'] = store.get_tools(doc.id, doc.version)
    snapshot['draft'] = body.draft
    saved = history.save(snapshot)
    return {'id': saved['id'], 'created': saved['created']}


@app.get('/api/history')
async def list_history():
    return history.listing()


@app.get('/api/history/{identifier}')
async def read_history(identifier: str):
    snapshot = history.get(identifier)
    if not snapshot:
        raise HTTPException(404, '历史记录不存在。')
    return snapshot


@app.post('/api/history/{identifier}/restore')
async def restore_history(identifier: str):
    snapshot = await read_history(identifier)
    # Fork the snapshot so editing it never mutates another live document.
    doc = Document.model_validate(snapshot['document'])
    doc.id = uuid.uuid4().hex
    store.put(doc)
    snapshot['document'] = doc.model_dump(mode='json')
    for name, output in snapshot.get('tools', {}).items():
        store.put_tool(doc.id, doc.version, name, output)
    if snapshot.get('result'):
        report_id = uuid.uuid4().hex
        snapshot['result'].update(document_id=doc.id, report_id=report_id)
        store.put_report(report_id, snapshot)
    return snapshot


@app.delete('/api/history/{identifier}', status_code=204)
async def remove_history(identifier: str):
    history.delete(identifier)


class WorkflowRequest(AnalysisRequest):
    confirmed: bool = False
    promises: str = Field(default='', max_length=6000)


@app.post('/api/workflow')
async def workflow(body: WorkflowRequest):
    """Explicit, inspectable orchestration; no unbounded autonomous actions."""
    return await run_contract_workflow(body, require_doc, report, promises)



if (ROOT / 'frontend' / 'dist').exists():
    app.mount('/', StaticFiles(directory=ROOT / 'frontend' / 'dist', html=True), name='frontend')
