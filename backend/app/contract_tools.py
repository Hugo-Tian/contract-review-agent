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
    if request.output_language:
        payload['output_language'] = request.output_language
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
    profile = current()
    # Ignore pagination/line wrapping, but preserve all non-whitespace characters.
    def lines(doc):
        result = []
        for block in doc.blocks:
            if 'compare_note' in profile.tools:
                # English text needs its word spaces; collapse runs of whitespace instead of deleting them.
                parts = [re.sub(r'\s+', ' ', part).strip() for part in profile.split_sentences(block.text)]
            else:
                parts = [re.sub(r'\s+', '', part) for part in re.split(r'(?<=[。；！？])', block.text)]
            result.extend((text, block.location) for text in parts if text)
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
            'note': profile.tools.get('compare_note', '逐句文字比较，忽略空格和换行；不比较图片、印章或版式。分页变化和OCR误字可能被标成改动，请回原件核对。')}


def cents(value):
    return value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def require_tool(name):
    if name not in current().tools:
        raise ValueError('当前地区没有这个工具。')
    return current().tools


def deposit(body):
    """Move-out settlement from user-confirmed figures only; never guesses or judges legality."""
    tools = require_tool('deposit_note')
    unit = current().currency['code']
    rows = [{**d.model_dump(mode='json'), 'amount': str(cents(d.amount))} for d in body.deductions]
    deductions = sum((d.amount for d in body.deductions), Decimal('0'))
    penalty = {'none': Decimal('0'), 'months_rent': body.monthly_rent * body.penalty_months,
               'fixed': body.penalty_amount, 'forfeit_deposit': body.deposit}[body.penalty_type]
    penalty = cents(penalty)
    held = body.deposit + body.prepaid_rent
    scenarios = []
    for title, fee in [('只扣欠租和你确认的扣减项', Decimal('0.00')), ('再按合约扣提前退租罚则', penalty)]:
        balance = cents(held - body.rent_arrears - deductions - fee)
        scenarios.append({'title': title, 'penalty': str(fee), 'balance': str(balance),
                          'estimated_return': str(max(balance, Decimal('0.00'))), 'excess_deductions': str(cents(max(-balance, Decimal('0')))),
                          'formula': f'{unit} {body.deposit} + {body.prepaid_rent} − {body.rent_arrears} − {cents(deductions)} − {fee} = {balance}'})
    return {'inputs': body.model_dump(mode='json'), 'deductions': rows, 'deductions_total': str(cents(deductions)),
            'penalty_type': body.penalty_type, 'scenarios': scenarios, 'currency': unit, 'note': tools['deposit_note']}


def upfront(body):
    tools = require_tool('upfront_note')
    unit = current().currency['code']
    stamp = cents(body.stamp_duty_total * body.stamp_duty_share / 100)
    commission = cents(body.commission_base * body.commission_rate / 100)
    others = sum((o.amount for o in body.others), Decimal('0'))
    total = cents(body.first_rent + body.deposit + stamp + commission + others)
    items = [{'name': '首期租金', 'amount': str(cents(body.first_rent)), 'formula': str(body.first_rent)},
             {'name': '按金', 'amount': str(cents(body.deposit)), 'formula': str(body.deposit)},
             {'name': '印花税（你分担的部分）', 'amount': str(stamp), 'formula': f'{body.stamp_duty_total} × {body.stamp_duty_share}%'},
             {'name': '中介佣金', 'amount': str(commission), 'formula': f'{body.commission_base} × {body.commission_rate}%'}]
    items += [{'name': o.name, 'amount': str(cents(o.amount)), 'formula': str(o.amount), 'basis': o.basis} for o in body.others]
    return {'inputs': body.model_dump(mode='json'), 'items': items, 'total': str(total), 'currency': unit,
            'formula': f'{unit} ' + ' + '.join(i['amount'] for i in items) + f' = {total}', 'note': tools['upfront_note']}


def checklist(doc, snapshot):
    """Offline, rule-based. Every item cites lease text it found, or says plainly what was not found."""
    tools = require_tool('checklist')
    result = snapshot.get('result') or {}
    if result.get('mode') != 'live':
        raise ValueError('核对清单需要真实分析报告；演示报告没有从租约提取事实。')
    facts = {f['label']: f for f in result['report']['facts']}
    masked = masked_document(doc)
    texts = {b.id: b.text for b in masked.blocks}
    _, catalog = evidence_catalog(masked)
    items = []

    def verified(evidence):
        # Report evidence was checked when the report was made; check again against this exact version.
        return [e for e in evidence if e['quote'] in texts.get(e['block_id'], '')]

    for rule in tools['checklist']:
        if 'fact' in rule:
            fact = facts.get(rule['fact'])
            evidence = verified(fact['evidence']) if fact and fact['value'] != '未发现明确约定' else []
            for label in rule['related']:
                related = facts.get(label)
                if evidence and related and related['value'] != '未发现明确约定':
                    evidence += verified(related['evidence'])
            source = rule['fact']
        else:
            pattern = re.compile(rule['keyword'], re.I)
            evidence = [e.model_dump() for e in catalog.values() if pattern.search(e.quote)][:3]
            source = '租约原文关键词'
        key = 'found' if evidence else 'missing'
        if key not in rule:
            continue
        title, why = rule[key]
        items.append({'title': title, 'why': why, 'basis': '租约原文' if evidence else '本次正文未找到', 'source': source, 'evidence': evidence})
    covered = {rule['fact'] for rule in tools['checklist'] if 'fact' in rule}
    for label, fact in facts.items():
        if label not in covered and fact['value'] == '未发现明确约定':
            items.append({'title': f'签约前问清：{label}', 'why': f'本次正文里没找到关于“{label}”的明确写法（只限本次导入的文字）。可以请对方说明，并要求写进租约。',
                          'basis': '本次正文未找到', 'source': label, 'evidence': []})
    text = json.dumps([{k: v for k, v in item.items() if k != 'evidence'} for item in items], ensure_ascii=False)
    if current().report_forbidden.search(text):
        raise ValueError('核对清单文案包含不允许的判断，请报告此问题。')
    return {'items': items, 'note': tools['checklist_note'], 'report_id': result['report_id']}
