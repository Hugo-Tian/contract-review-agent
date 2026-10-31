import json
import os
import re
import ssl
import httpx
from pydantic import ValidationError
from .schemas import Document, Report, Evidence, Fact, Issue, Context, ModelReport, EvidenceReference
from .profiles import current, cn

# Mainland prompt, kept under its old name for existing imports; analysis uses the active profile.
SYSTEM = cn.SYSTEM


def configured():
    return bool(os.getenv('MODEL_API_KEY') and os.getenv('MODEL_NAME'))


def redact(text: str) -> str:
    return current().redact(text)


def masked_document(doc: Document):
    copy = doc.model_copy(deep=True)
    for block in copy.blocks:
        block.text = redact(block.text)
        block.original_text = None
    return copy


class ReportCheckError(ValueError):
    def __init__(self, errors):
        self.errors_detail = errors
        super().__init__('；'.join(errors))


def restore_layout_quotes(report: Report, doc: Document):
    """Restore only uniquely matching whitespace differences, never fuzzy wording."""
    def indexed(text):
        chars, positions = [], []
        for i, ch in enumerate(text):
            if ch.isspace():
                continue
            chars.append(ch)
            positions.append(i)
        return ''.join(chars), positions

    blocks = {b.id: b for b in doc.blocks}
    for item in [*report.facts, *report.issues]:
        for e in item.evidence:
            b = blocks.get(e.block_id)
            if not b or e.location != b.location or e.quote in b.text:
                continue
            needle, _ = indexed(e.quote)
            haystack, indices = indexed(b.text)
            start = haystack.find(needle)
            if not needle or start < 0 or haystack.find(needle, start + 1) >= 0:
                continue
            candidate = b.text[indices[start]:indices[start + len(needle) - 1] + 1]
            # Whitespace between ASCII words/numbers is meaningful; do not join it.
            boundaries = lambda value: re.findall(r'[A-Za-z0-9]+', value)
            if boundaries(candidate) != boundaries(e.quote):
                continue
            e.quote = candidate
    return report


def validate_evidence(report: Report, doc: Document):
    blocks = {b.id: b for b in doc.blocks}
    errors = []
    if sorted(f.label for f in report.facts) != sorted(current().fact_labels):
        errors.append('facts：合同事实字段不完整或重复。')
    for i, fact in enumerate(report.facts):
        if not fact.evidence and fact.value != '未发现明确约定':
            errors.append(f'facts[{i}].evidence：事实缺少证据；若全文未发现明确约定，value必须恰为“未发现明确约定”，否则附原文引用。')
        if fact.value == '未发现明确约定' and fact.evidence:
            errors.append(f'facts[{i}].evidence：缺失事实不得编造引用。')
    for i, issue in enumerate(report.issues):
        if issue.status == '信息缺失':
            if issue.evidence:
                errors.append(f'issues[{i}].evidence：信息缺失不得带伪造引用。')
        elif not issue.evidence:
            errors.append(f'issues[{i}].evidence：风险结论缺少证据。')
        if issue.status == '条款冲突' and len({(e.block_id, e.quote) for e in issue.evidence}) < 2:
            errors.append(f'issues[{i}].evidence：冲突判断必须有至少两个不同原文片段。')
    for group in ('facts', 'issues'):
        for i, item in enumerate(getattr(report, group)):
            for j, e in enumerate(item.evidence):
                block = blocks.get(e.block_id)
                path = f'{group}[{i}].evidence[{j}]'
                if not block:
                    errors.append(path + '.block_id：文本块不存在。')
                elif e.location != block.location:
                    errors.append(path + '.location：位置不匹配。')
                elif not e.quote.strip() or e.quote not in block.text:
                    errors.append(path + '.quote：引用不是该块连续原文，请从该块复制较短的逐字片段，勿改写、拼接或省略。')
    # A structural safety backstop; it cannot establish semantic correctness.
    generated = report.model_dump()
    for item in [*generated['facts'], *generated['issues']]:
        item.pop('evidence', None)
    text = json.dumps(generated, ensure_ascii=False)
    if current().report_forbidden.search(text):
        errors.append('report：结果包含未经核验的法律或外部来源内容。')
    if errors:
        raise ReportCheckError(errors)
    return report


def normalize_missing_references(report: Report, doc: Document):
    """Related text cannot prove absence. Verify it first, then omit that citation.

    Never repair invented IDs, locations or quotes. This only removes contextual
    references from missing-information findings; it does not change the finding.
    """
    blocks = {b.id: b for b in doc.blocks}
    for i, issue in enumerate(report.issues):
        if issue.status == '信息缺失':
            for j, e in enumerate(issue.evidence):
                b = blocks.get(e.block_id)
                if not b or e.location != b.location or not e.quote.strip() or e.quote not in b.text:
                    raise ReportCheckError([f'issues[{i}].evidence[{j}]：信息缺失条目的相关引用不真实，不能展示；请核对原文或用空 evidence 表达全文缺失。'])
            issue.evidence = []
    return report


def demo_report(doc: Document) -> Report:
    # Deliberately a UI demonstration, not keyword rules posing as an AI review.
    first = doc.blocks[0]
    demo = current().demo
    return Report(
        summary=demo['summary'],
        facts=[Fact(label=label, value='演示模式未提取', evidence=[]) for label in current().fact_labels],
        issues=[Issue(title=demo['title'], level='低', reason=demo['reason'],
                      evidence=[Evidence(block_id=first.id, quote=first.text[:100], location=first.location)],
                      explanation=demo['explanation'], impact=demo['impact'],
                      status='明确约定', question=demo['question'], negotiation=demo['negotiation'])],
        questions=list(demo['questions']),
        amendments=list(demo['amendments']),
        message=demo['message'])


class ModelFailure(Exception):
    pass


def evidence_catalog(doc: Document):
    """Partition every character into deterministic excerpts; never truncate text."""
    payload, catalog = [], {}
    for block in doc.blocks:
        passages = []
        pieces = current().split_sentences(block.text)
        for piece in pieces:
            # Bound excerpts while preserving every original character in sequence.
            while piece:
                end = min(450, len(piece))
                if len(piece) > end:
                    split = piece.rfind('\n', 100, end)
                    if split >= 0:
                        end = split + 1
                text, piece = piece[:end], piece[end:]
                quote_id = f'q{len(passages)+1:03}'
                passages.append({'quote_id': quote_id, 'text': text})
                catalog[(block.id, quote_id)] = Evidence(block_id=block.id, quote=text, location=block.location)
        payload.append({'id': block.id, 'source': block.source, 'location': block.location, 'passages': passages})
    return payload, catalog


def resolve_references(result: ModelReport, catalog):
    data = result.model_dump()
    errors = []
    for group in ('facts', 'issues'):
        for i, item in enumerate(data[group]):
            resolved = []
            for j, ref in enumerate(item['evidence']):
                evidence = catalog.get((ref['block_id'], ref['quote_id']))
                if evidence is None:
                    errors.append(f'{group}[{i}].evidence[{j}]：原文片段编号不存在，请仅选择blocks.passages提供的block_id与quote_id组合。')
                else:
                    resolved.append(evidence.model_dump())
            item['evidence'] = resolved
    if errors:
        raise ReportCheckError(errors)
    return Report.model_validate(data)


async def analyze(doc: Document, context: Context):
    profile = current()
    if profile.system is None:
        raise ModelFailure(profile.messages['not_ready'])
    masked = masked_document(doc)
    blocks, catalog = evidence_catalog(masked)
    payload = {'blocks': blocks,
               'coverage': doc.coverage, 'warnings': doc.warnings,
               'context': {k: redact(str(v)) for k, v in context.for_model().items()},
               'required_facts': list(profile.fact_labels), 'schema': ModelReport.model_json_schema()}
    body = {'model': os.environ['MODEL_NAME'], 'messages': [
        {'role': 'system', 'content': profile.system},
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]}
    if os.getenv('MODEL_RESPONSE_FORMAT', 'json_object') == 'json_schema':
        body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'contract_report', 'strict': True, 'schema': ModelReport.model_json_schema()}}
    else:
        body['response_format'] = {'type': 'json_object'}
    if os.getenv('MODEL_THINKING') in ('enabled', 'disabled'):
        body['thinking'] = {'type': os.environ['MODEL_THINKING']}
    if os.getenv('MODEL_MAX_TOKENS'):
        body['max_tokens'] = int(os.environ['MODEL_MAX_TOKENS'])
    async with httpx.AsyncClient(timeout=float(os.getenv('MODEL_TIMEOUT_SECONDS', '90')), follow_redirects=False,
                                 trust_env=os.getenv('MODEL_TRUST_ENV', 'true').lower() == 'true') as client:
        for attempt in range(2):
            content = None
            try:
                response = await client.post(os.getenv('MODEL_BASE_URL', 'https://api.openai.com/v1').rstrip('/') + '/chat/completions',
                                             headers={'Authorization': 'Bearer ' + os.environ['MODEL_API_KEY']}, json=body)
            except httpx.TimeoutException:
                raise ModelFailure('模型请求超时，未生成报告，请稍后重试。') from None
            except (httpx.HTTPError, ssl.SSLError):
                raise ModelFailure('无法连接模型服务，请检查后端地址和网络。') from None
            if response.status_code == 429:
                raise ModelFailure('模型服务限流或额度不足，未生成报告。')
            if response.status_code in (401, 403):
                raise ModelFailure('模型鉴权失败，请检查后端密钥和权限。')
            if response.status_code != 200:
                raise ModelFailure(f'模型服务返回 HTTP {response.status_code}，请检查接口、模型和 JSON 格式支持。')
            try:
                choice = response.json()['choices'][0]
                if choice.get('finish_reason') != 'stop':
                    raise ValueError('模型输出未完整结束。')
                content = choice['message']['content']
                report = resolve_references(ModelReport.model_validate_json(content), catalog)
                normalize_missing_references(report, masked)
                validate_evidence(report, masked)
                return report
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                if isinstance(exc, ValidationError):
                    known = set(Report.model_fields) | set(Fact.model_fields) | set(Issue.model_fields) | set(EvidenceReference.model_fields)
                    detail = json.dumps([{'field': [p if isinstance(p, int) or p in known else '?' for p in e['loc']], 'type': e['type']} for e in exc.errors(include_input=False)][:12], ensure_ascii=False)
                elif isinstance(exc, ReportCheckError) or type(exc) is ValueError:
                    detail = str(exc)
                else:
                    detail = '响应缺少完整 choices/message/content。'
                if attempt:
                    raise ModelFailure('模型输出结构或证据校验失败（已重试一次）。具体原因：' + detail[:1400] + ' 未展示为有效报告；请重试或核对正文。') from None
                if isinstance(content, str):
                    body['messages'].append({'role': 'assistant', 'content': content})
                body['messages'].append({'role': 'user', 'content': '上一次输出未通过校验，原因：' + detail + ' 请修复上一版并返回完整 JSON。每个evidence只能有block_id和quote_id，从blocks.passages选择，禁止抄写quote/location。status=信息缺失时evidence=[]。facts缺失值必须恰为未发现明确约定。不得提供未经核验的法律条文。'})
