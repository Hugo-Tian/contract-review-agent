"""SDK graph; sensitive data stays in request-local closures, not SDK trace inputs."""
import uuid
from importlib.metadata import version
from fastapi import HTTPException
from openjiuwen.core.workflow import Workflow, WorkflowCard, WorkflowComponent, create_workflow_session
from openjiuwen.core.session import WORKFLOW_EXECUTE_TIMEOUT
from .schemas import AnalysisRequest
from .tool_schemas import PromiseRequest
from . import store, legal

SDK_VERSION = version('openjiuwen')
NODE_IDS = ('confirm', 'analyze', 'promises', 'legal', 'finalize')

class TaskNode(WorkflowComponent):
    def __init__(self, name, action, state):
        super().__init__()
        self.name, self.action, self.state = name, action, state

    async def invoke(self, inputs, session, context):
        if self.state.get('error'):
            return {'status': 'skipped'}
        try:
            await self.action()
            self.state['executed'].append(self.name)
            return {'status': 'completed'}
        except (HTTPException, ValueError) as exc:
            self.state['error'] = exc
            return {'status': 'failed'}
        except Exception:
            self.state['error'] = HTTPException(500, '任务节点执行失败，请重试。')
            return {'status': 'failed'}

async def run_contract_workflow(body, require_doc, report, promises):
    doc = None
    trace, references = [], []
    output = promise_output = None
    state = {'executed': []}

    async def confirm():
        nonlocal doc, trace, output, promise_output, references
        doc = require_doc(body.document_id, body.version)
        if not body.confirmed:
            raise HTTPException(400, '请先核对提取正文和金额。')
        trace = [{'name': '正文核对', 'status': '完成', 'detail': f'用户确认版本 {doc.version}，共 {len(doc.blocks)} 个文本块。'}]

    async def analyze():
        nonlocal doc, trace, output, promise_output, references
        base = AnalysisRequest(**body.model_dump(exclude={'confirmed', 'promises'}))
        output = await report(base)
        require_doc(doc.id, doc.version)
        trace.append({'name': '合同分析与引用核验', 'status': '完成', 'detail': '演示布局，不做风险判断。' if body.mode == 'demo' else '引用出处已校验；解释仍需人工复核。'})

    async def promises_step():
        nonlocal doc, trace, output, promise_output, references
        promise_output = None
        if body.promises.strip() and body.mode == 'live':
            store.delete_tool(doc.id, doc.version, 'promises')
            try:
                promise_output = await promises(PromiseRequest(document_id=doc.id, version=doc.version, promises=body.promises, consent=body.consent))
                trace.append({'name': '销售承诺核验', 'status': '完成', 'detail': '已逐条对照合同；结果见销售承诺工具。'})
            except (HTTPException, ValueError) as exc:
                trace.append({'name': '销售承诺核验', 'status': '失败', 'detail': str(exc.detail) if isinstance(exc, HTTPException) else str(exc)})
        else:
            trace.append({'name': '销售承诺核验', 'status': '跳过', 'detail': '未提供销售说法，或当前为演示模式。'})

    async def legal_step():
        nonlocal doc, trace, output, promise_output, references
        references = []
        if body.mode == 'live':
            query = '退款 违约金' if body.context.goal == '了解退款' else '格式条款 承诺'
            try:
                found = legal.search(query)
                references = found['results'][:3]
                trace.append({'name': '法规参考检索', 'status': '完成', 'detail': f'本机选编检索“{query}”，显示 {len(references)} 条参考；不自动认定适用。'})
            except (OSError, ValueError, KeyError):
                trace.append({'name': '法规参考检索', 'status': '失败', 'detail': '本机法规缓存暂不可用，请在法规工具中重试。'})
        else:
            trace.append({'name': '法规参考检索', 'status': '跳过', 'detail': '演示模式不生成法律参考结论。'})

    async def finalize():
        nonlocal doc, trace, output, promise_output, references
        trace.append({'name': '退款与下一步', 'status': '待确认', 'detail': '如需试算，请在退款工具核对实付、已用服务及扣费依据；系统不猜金额。草稿由你检查后自行发送。'})
        require_doc(doc.id, doc.version)
        output['workflow'] = {'engine': 'openJiuwen', 'sdk_version': SDK_VERSION, 'nodes': list(NODE_IDS), 'trace': trace, 'references': references, 'partial': any(t['status'] == '失败' for t in trace), 'promises': promise_output}
        snapshot = store.get_report(output['report_id'])
        if not snapshot:
            raise HTTPException(409, '任务期间文档已失效，请重新导入。')
        snapshot['result'] = output
        store.put_report(output['report_id'], snapshot)

    actions = (confirm, analyze, promises_step, legal_step, finalize)
    flow = Workflow(card=WorkflowCard(id='mingyue-contract', name='明约合同核验', version='1.0'))
    for index, (name, action) in enumerate(zip(NODE_IDS, actions)):
        node = TaskNode(name, action, state)
        if index == 0:
            flow.set_start_comp(name, node)
        elif index == len(NODE_IDS) - 1:
            flow.set_end_comp(name, node)
        else:
            flow.add_workflow_comp(name, node)
        if index:
            flow.add_connection(NODE_IDS[index - 1], name)
    session = create_workflow_session(session_id=uuid.uuid4().hex, envs={WORKFLOW_EXECUTE_TIMEOUT: 1800})
    await flow.invoke({}, session)
    if state.get('error'):
        raise state['error']
    if state['executed'] != list(NODE_IDS) or output is None:
        raise HTTPException(502, 'SDK工作流未完整结束，请重试。')
    return output
