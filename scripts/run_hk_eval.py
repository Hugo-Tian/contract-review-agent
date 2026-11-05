"""Run eval/hk_cases.json against the configured model (REGION=hk). Fictional cases only.

From the backend directory:
    ..\\.venv-jiuwen\\Scripts\\python.exe ..\\scripts\\run_hk_eval.py

Writes each case's full output to work/hk-eval/<id>.json and a run summary to work/hk-eval/summary.json.
Judging the expected points and forbidden conclusions is done by a person reading those files;
this script only records what the model returned, whether validation passed, time and token usage.
"""
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
os.environ['REGION'] = 'hk'
from app import main, contract_tools  # noqa: E402,F401  (main loads backend/.env)
from app.analysis import analyze, configured, usage_meter, ModelFailure  # noqa: E402
from app.schemas import Context, Document, Block  # noqa: E402
from app.tool_schemas import PromiseRequest  # noqa: E402

OUT = ROOT / 'work' / 'hk-eval'


def document(*parts):
    identifier = uuid.uuid4().hex
    blocks = [Block(id=f'{identifier}-b{i}', location=label, text=text, source='paste') for i, (label, text) in enumerate(parts, 1)]
    return Document(id=identifier, name='虚构评测样本', kind='text', blocks=blocks, coverage=f'虚构评测样本，共 {len(blocks)} 段')


async def metered(call):
    token = usage_meter.set({})
    start = time.perf_counter()
    try:
        result, status = await call, 'ok'
    except ModelFailure as exc:
        result, status = {'error': str(exc)}, 'model_failure'
    finally:
        usage = usage_meter.get()
        usage_meter.reset(token)
    return {'status': status, 'seconds': round(time.perf_counter() - start, 1), 'usage': usage,
            'output': result.model_dump() if hasattr(result, 'model_dump') else result}


async def run_case(case):
    context = Context(**case.get('context', {}))
    record = {'id': case['id'], 'context': context.for_model()}
    if case.get('tool') == 'promises':
        doc = document(('第1段', case['text']))
        request = PromiseRequest(document_id=doc.id, version=1, promises='\n'.join(case['promises']), consent=True,
                                 output_language=context.output_language)
        record['promises'] = await metered(contract_tools.compare_promises(doc, request))
    elif case.get('tool') == 'compare':
        temporary, formal = document(('临时租约', case['text'])), document(('正式租约', case['paired_with']))
        record['compare'] = contract_tools.compare_versions(temporary, formal)
        record['analysis'] = await metered(analyze(document(('临时租约', case['text']), ('正式租约', case['paired_with'])), context))
    else:
        doc = document(('第1段', case['text']))
        record['analysis'] = await metered(analyze(doc, context))
        if record['analysis']['status'] == 'ok':
            # The pre-signing checklist the app would build from this report (same process, same pseudonyms).
            snapshot = {'result': {'mode': 'live', 'report_id': 'eval', 'report': record['analysis']['output']}}
            record['checklist'] = [{'title': i['title'], 'basis': i['basis'], 'quotes': len(i['evidence'])}
                                   for i in contract_tools.checklist(doc, snapshot)['items']]
    return record


async def main_run():
    if not configured():
        raise SystemExit('backend/.env 未配置模型。')
    OUT.mkdir(parents=True, exist_ok=True)
    cases = json.loads((ROOT / 'eval' / 'hk_cases.json').read_text(encoding='utf-8'))
    only = sys.argv[sys.argv.index('--only') + 1].split(',') if '--only' in sys.argv else None  # e.g. --only hk-injection
    cases = [c for c in cases if not only or c['id'] in only]
    summary = {'model': os.getenv('MODEL_NAME'), 'started': datetime.now(timezone.utc).isoformat(), 'cases': []}
    for case in cases:
        record = await run_case(case)
        (OUT / f"{case['id']}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding='utf-8')
        runs = [record[k] for k in ('analysis', 'promises') if k in record]
        summary['cases'].append({'id': case['id'], 'status': [r['status'] for r in runs], 'seconds': sum(r['seconds'] for r in runs),
                                 'tokens': sum((r['usage'] or {}).get('total_tokens', 0) for r in runs),
                                 'calls': sum((r['usage'] or {}).get('calls', 0) for r in runs)})
        print(case['id'], summary['cases'][-1], flush=True)
    (OUT / ('summary.json' if not only else 'summary-partial.json')).write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')


asyncio.run(main_run())
