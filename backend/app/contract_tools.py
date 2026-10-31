import json
import os
import ssl
import re
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
import httpx
from .analysis import masked_document, evidence_catalog, redact, ModelFailure
from .tool_schemas import PromiseResult
from .profiles import current


async def compare_promises(doc, request):
    profile = current().promise
    if profile['system'] is None:
        raise ModelFailure(current().messages['not_ready'])
    promises = [line.strip() for line in request.promises.splitlines() if line.strip()]
    if not promises or len(promises) > 30:
        raise ValueError('每行填写一条承诺，一次最多 30 条。')
    blocks, catalog = evidence_catalog(masked_document(doc))
    payload = {'promises': [{'promise_id': i, 'text': redact(p)} for i, p in enumerate(promises, 1)], 'blocks': blocks,
               'schema': PromiseResult.model_json_schema(), 'coverage': doc.coverage}
    system = profile['system']
    body = {'model': os.environ['MODEL_NAME'], 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}], 'response_format': {'type': 'json_object'}, 'max_tokens': 7000}
    if os.getenv('MODEL_THINKING') in ('enabled', 'disabled'):
        body['thinking'] = {'type': os.environ['MODEL_THINKING']}
    async with httpx.AsyncClient(timeout=120, trust_env=os.getenv('MODEL_TRUST_ENV', 'true').lower() == 'true') as client:
        for attempt in range(2):
            try:
                response = await client.post(os.getenv('MODEL_BASE_URL', 'https://api.deepseek.com').rstrip('/') + '/chat/completions', headers={'Authorization': 'Bearer ' + os.environ['MODEL_API_KEY']}, json=body)
                response.raise_for_status()
            except (httpx.HTTPError, ssl.SSLError):
                raise ModelFailure(profile['connect_error']) from None
            content = None
            try:
                choice = response.json()['choices'][0]
                if choice.get('finish_reason') != 'stop':
                    raise ValueError('输出不完整')
                content = choice['message']['content']
                result = PromiseResult.model_validate_json(content)
                if sorted(i.promise_id for i in result.items) != list(range(1, len(promises) + 1)):
                    raise ValueError('承诺条目遗漏或重复')
                rows = []
                for item in sorted(result.items, key=lambda x: x.promise_id):
                    if profile['forbidden'].search(item.explanation + item.question):
                        raise ValueError('解释含未经核验的外部法律内容')
                    if item.status in ('合同有写', '说法不一致') and not item.evidence:
                        raise ValueError('对照结论缺少引用')
                    if item.status == '合同没找到' and item.evidence:
                        raise ValueError('未找到不能带引用')
                    refs = []
                    for ref in item.evidence:
                        e = catalog.get((ref.block_id, ref.quote_id))
                        if not e:
                            raise ValueError('引用编号不存在')
                        refs.append(e.model_dump())
                    rows.append({**item.model_dump(exclude={'evidence'}), 'promise': promises[item.promise_id - 1], 'evidence': refs})
                return {'source': request.source, 'items': rows, 'note': profile['note']}
            except (ValueError, KeyError, TypeError, IndexError):
                if attempt:
                    raise ModelFailure(profile['check_error']) from None
                if isinstance(content, str):
                    body['messages'].append({'role': 'assistant', 'content': content})
                body['messages'].append({'role': 'user', 'content': profile['retry']})


def refund(body):
    cents = lambda n: n.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    rows = [{**s.model_dump(mode='json'), 'subtotal': str(cents(s.quantity * s.unit_price))} for s in body.services]
    service_total = sum((Decimal(r['subtotal']) for r in rows), Decimal('0'))
    penalty = cents(body.penalty_base * body.penalty_rate / 100)
    available = body.paid - body.already_refunded
    scenarios = []
    for title, fee in [('只扣已用服务费用', Decimal('0')), ('已用服务费用和违约金都扣', penalty)]:
        balance = available - service_total - fee
        scenarios.append({'title': title, 'service_cost': str(service_total), 'penalty': str(fee), 'balance': str(cents(balance)),
                          'estimated_refund': str(cents(max(balance, Decimal('0')))), 'excess_deductions': str(cents(max(-balance, Decimal('0')))),
                          'formula': f'{body.paid} − {body.already_refunded} − {service_total} − {fee} = {cents(balance)}'})
    return {'inputs': body.model_dump(mode='json'), 'services': rows, 'scenarios': scenarios,
            'note': '这是按你填的条件试算，不是最终可退金额。服务是否应扣、单价是否合适、违约金是否同时扣，需要另行确认。扣费超过剩余款项不代表你还欠这笔钱。'}


def compare_versions(left, right):
    # Ignore pagination/line wrapping, but preserve all non-whitespace characters.
    def lines(doc):
        import re
        result = []
        for block in doc.blocks:
            for part in re.split(r'(?<=[。；！？])', block.text):
                text = re.sub(r'\s+', '', part)
                if text:
                    result.append((text, block.location))
        return result
    a, b = lines(left), lines(right)
    if sum(len(t) for t, _ in a + b) > 100000:
        raise ValueError('两版文字合计超过 10 万字符，请拆分后比较。')
    changes = []
    matcher = SequenceMatcher(None, [v[0] for v in a], [v[0] for v in b], autojunk=False)
    for kind, i, j, k, l in matcher.get_opcodes():
        if kind != 'equal':
            changes.append({'kind': {'replace': '修改', 'delete': '删除', 'insert': '新增'}[kind],
                            'before': [{'text': t, 'location': loc} for t, loc in a[i:j]],
                            'after': [{'text': t, 'location': loc} for t, loc in b[k:l]]})
    return {'left': {'name': left.name, 'version': left.version}, 'right': {'name': right.name, 'version': right.version}, 'changes': changes,
            'note': '逐句文字比较，忽略空格和换行；不比较图片、印章或版式。分页变化和OCR误字可能被标成改动，请回原件核对。'}
