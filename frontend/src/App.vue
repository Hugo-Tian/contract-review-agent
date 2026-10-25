<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import type { Document, Result, Evidence } from './types'
import ToolsPanel from './ToolsPanel.vue'
const ocrMode=ref('auto'), restoredTools=ref<any>(null), toolBusy=ref(false)
function restoreSnapshot(snapshot:any){setDoc(snapshot.document);if(snapshot.context)Object.assign(context,snapshot.context);result.value=snapshot.result;message.value=snapshot.draft||snapshot.result?.report.message||'';step.value=snapshot.result?3:2;nextTick(()=>restoredTools.value=snapshot.tools||{})}

const factLabels:Record<string,string> = {'签约主体':'和谁签合同','收款主体':'钱付给谁','成交金额':'合同总价','分项价格':'各项服务怎么收费','服务期限':'服务到什么时候','服务内容':'机构提供什么服务','交付标准':'做到什么才算完成','退款条件':'什么情况下可以退费','违约责任':'没按约定做怎么办','争议解决':'有争议怎么处理'}
const statusLabels:Record<string,string> = {'明确约定':'合同写明了','表述含糊':'这里没说清楚','条款冲突':'前后说法不一致','信息缺失':'本次正文里没找到'}
const levelLabels:Record<string,string> = {'高':'优先问清楚','中':'建议问清楚','低':'了解一下'}
const step = ref(1), busy = ref(''), error = ref(''), toast = ref('')
const health = ref({model_configured:false,max_analysis_chars:24000})
const text = ref(''), doc = ref<Document|null>(null), result = ref<Result|null>(null)
const edits = reactive<Record<string,string>>({}), confirmed = ref(false), consent = ref(false)
const mode = ref<'demo'|'live'>('demo'), highlighted = ref(''), outbound = ref<Document|null>(null)
const message = ref(''), style = ref('礼貌直接')
const context = reactive({role:'学员',goal:'签约前检查',signed:'未知',paid:'未知',amount:'',signed_date:'',paid_date:'',services:'',preferences:''})
const dirty = computed(()=>doc.value?.blocks.some(b=>edits[b.id] !== b.text) ?? false)
const length = computed(()=>doc.value?.blocks.reduce((n,b)=>n+b.text.length,0) ?? 0)

async function api<T>(path:string, options:RequestInit={}):Promise<T> {
  const response = await fetch('/api'+path, options)
  if(!response.ok) { const body = await response.json().catch(()=>({detail:'服务暂时不可用'})); throw new Error(body.detail || '请求失败') }
  return response.status===204 ? undefined as T : await response.json()
}
function json(method:string, body:unknown) {return {method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}}
async function work(label:string, fn:()=>Promise<void>) {if(busy.value||toolBusy.value)return;busy.value=label;error.value='';try{await fn()}catch(e){error.value=e instanceof Error?e.message:'操作失败，请重试'}finally{busy.value=''}}
function setDoc(value:Document){restoredTools.value=null;doc.value=value;for(const key of Object.keys(edits))delete edits[key];for(const b of value.blocks)edits[b.id]=b.text;confirmed.value=false;consent.value=false;outbound.value=null;result.value=null;step.value=2}
async function importText(){await work('正在整理粘贴文本…', async()=>setDoc(await api<Document>('/documents/text',json('POST',{text:text.value}))))}
async function upload(event:Event){const input=event.target as HTMLInputElement;const file=input.files?.[0];if(!file)return;if(file.size>10*1024*1024){error.value='文件超过 10 MB 限制';input.value='';return}await work('正在提取正文和本机OCR，最长等待180秒…',async()=>setDoc(await api<Document>('/documents/upload?name='+encodeURIComponent(file.name)+'&ocr='+ocrMode.value,{method:'POST',body:file,headers:{'Content-Type':'application/octet-stream'}})));input.value=''}
function sample(){text.value='虚构示例｜星桥求职辅导服务合同\n第一条 签约主体为星桥示例教育有限公司，收款主体为星桥示例教育有限公司。\n第二条 服务期为2026年11月1日至2027年4月30日，优惠成交价为人民币9800元。\n第三条 简历修改2次，每次反馈不晚于3个工作日；一对一辅导4次，每次60分钟。\n第四条 建立服务群并开通学习账号，即视为课程包全部交付。课程包分项标价6000元，一对一辅导分项标价8000元。\n第五条 提前退出按分项标价扣除已提供服务，另扣成交价20%的违约金。\n第六条 申请退款需提供学习记录，审核和到账期限另行通知。\n第七条 不保证正式录用，面试通过不等于录用。岗位推荐地区和数量以附件一为准，附件一未随本样例提供。\n第八条 争议由双方协商处理。所有名称与交易均为虚构。'}
async function save(){if(!doc.value)return;await work('正在保存正文修订…',async()=>setDoc(await api<Document>('/documents/'+doc.value!.id,json('PATCH',{version:doc.value!.version,edits}))))}
async function preview(){if(!doc.value)return;await work('正在生成脱敏预览…',async()=>{outbound.value=await api<Document>('/documents/'+doc.value!.id+'/outbound')})}
async function run(){if(!doc.value)return;await work(mode.value==='demo'?'正在生成演示布局…':'正在请求模型并校验引用，可能需要数分钟…',async()=>{result.value=await api<Result>('/analyze',json('POST',{document_id:doc.value!.id,version:doc.value!.version,mode:mode.value,context,consent:consent.value}));message.value=result.value.report.message;step.value=3;window.scrollTo({top:0})})}
async function locate(e:Evidence){highlighted.value=e.block_id;await nextTick();document.getElementById('source-'+e.block_id)?.scrollIntoView({behavior:'smooth',block:'center'})}
async function copy(){try{await navigator.clipboard.writeText(message.value);toast.value='沟通草稿已复制';setTimeout(()=>toast.value='',2500)}catch{error.value='无法访问剪贴板，请选中草稿后手动复制。'}}
function adjust(){if(!result.value)return;message.value=style.value==='简短询问'?'您好，想请您书面确认：'+result.value.report.questions.slice(0,3).join(' ')+' 谢谢。':style.value==='明确协商'?'您好，为便于双方确认，我希望进一步明确以下事项：\n'+result.value.report.questions.join('\n')+'\n以上补充内容希望与贵方协商后写入协议，请您确认。':result.value.report.message}
async function reset(){await work('正在清除临时文档…',async()=>{if(doc.value)await api('/documents/'+doc.value.id,{method:'DELETE'});doc.value=null;result.value=null;outbound.value=null;text.value='';message.value='';for(const key of Object.keys(edits))delete edits[key];Object.assign(context,{role:'学员',goal:'签约前检查',signed:'未知',paid:'未知',amount:'',signed_date:'',paid_date:'',services:'',preferences:''});step.value=1})}
onMounted(()=>work('正在连接本地服务…',async()=>{health.value=await api('/health');mode.value=health.value.model_configured?'live':'demo'}))
</script>

<template>
  <header class="topbar"><a class="brand" href="/" aria-label="明约首页"><span class="brand-icon">约</span><strong>明约</strong><span>合同阅读助手</span></a><span class="local"><i></i> 单用户本地工作台</span></header>
  <main>
    <div class="intro"><div><p class="audience">培训与求职辅导合同</p><h1>先看清约定，<br class="mobile-break">再做决定。</h1><p>把服务承诺、退出成本和待确认事项，放回原文里看。</p></div><div class="intro-note"><span class="small-heading">阅读的三个重点</span><p>交付什么 <span>／</span> 如何退出 <span>／</span> 还需问什么</p><small>辅助阅读与协商，不提供退款或就业结果保证。</small></div></div>
    <nav class="steps" aria-label="处理步骤"><button v-for="(label,index) in ['导入与背景','核对提取正文','阅读报告']" :key="label" :class="{active:step===index+1,done:step>index+1}" :disabled="(!!busy||toolBusy) || (index===1&&!doc) || (index===2&&!result)" @click="step=index+1"><span>{{index+1}}</span>{{label}}</button></nav>
    <div v-if="error" class="notice error" role="alert">{{error}}<button @click="error=''" aria-label="关闭提示">×</button></div>
    <div v-if="busy" class="notice progress" role="status"><span class="spinner"></span>{{busy}}</div>
    <div v-if="toast" class="toast" role="status">{{toast}}</div>

    <p v-if="dirty" class="notice">正文有尚未保存的修改，请先保存新版本，再使用合同工具。</p>
    <ToolsPanel :inert="!!busy||dirty" @busy="toolBusy=$event" :doc="doc" :result="result" :restored-tools="restoredTools" :draft="message" @restore="restoreSnapshot" @import="step=1" />
    <section v-if="step===1" class="input-grid">
      <div class="paper"><div class="section-heading"><h2>导入你的合同</h2><span>PDF / DOCX / 图片 / 文本</span></div>
        <div v-if="doc" class="notice">已载入「{{doc.name}}」。<button :disabled="(!!busy||toolBusy)" @click="step=2">继续核对</button><button :disabled="(!!busy||toolBusy)" @click="reset">清除后重新导入</button></div>
        <template v-else><label>PDF文字提取方式<select v-model="ocrMode"><option value="auto">自动：缺少文字的页面做OCR</option><option value="force">整份OCR：适合混合页面或文字提取异常</option><option value="off">只提取已有文字，不做OCR</option></select></label><label class="upload"><span class="upload-icon">↥</span><strong>选择合同文件</strong><span>最大 10 MB，PDF 最多 80 页</span><small>支持扫描件和照片，本机OCR一次最多20页</small><input type="file" accept=".pdf,.docx,.png,.jpg,.jpeg,.webp" :disabled="(!!busy||toolBusy)" @change="upload"></label>
        <div class="or"><span>或者粘贴正文</span></div><label for="contract" class="sr-only">合同正文</label><textarea id="contract" v-model="text" rows="9" maxlength="250000" placeholder="把合同内容粘贴到这里，保留条款编号、金额和表格对应关系。"></textarea>
        <div class="actions"><button class="link-button" @click="sample" :disabled="(!!busy||toolBusy)">填入虚构示例</button><button class="primary" @click="importText" :disabled="!text.trim()||(!!busy||toolBusy)">提取并核对正文</button></div></template>
        <p class="privacy">原文件不落盘。未保存的正文在本机临时保留1小时；手动保存的历史保留到你主动删除。OCR在本机运行，调用模型前需另行确认。</p>
      </div>
      <aside class="paper background"><h2>补充你的情况</h2><p class="muted">不知道的可以留空，不会自动推断已签约或已使用服务。</p>
        <div class="form-row"><label>你的立场<select v-model="context.role"><option>学员</option><option>付款家长</option></select></label><label>这次想了解<select v-model="context.goal"><option>签约前检查</option><option>付款后核对</option><option>了解退款</option></select></label></div>
        <div class="form-row"><label>是否签约<select v-model="context.signed"><option>未知</option><option>是</option><option>否</option></select></label><label>是否付款<select v-model="context.paid"><option>未知</option><option>是</option><option>否</option></select></label></div>
        <label>实际付款金额（元）<input v-model="context.amount" inputmode="decimal" maxlength="40" placeholder="留空表示未知"></label>
        <div class="form-row"><label>签约日期<input type="date" v-model="context.signed_date"></label><label>付款日期<input type="date" v-model="context.paid_date"></label></div>
        <label>已经接受的服务<textarea v-model="context.services" maxlength="2000" rows="3" placeholder="例如：已建群、开通账号，但未看课；简历修改过一次。"></textarea></label>
        <label>求职偏好及其他背景<textarea v-model="context.preferences" maxlength="2000" rows="2" placeholder="地区、岗位、学历专业、用工形式等。请勿填写不必要的个人信息。"></textarea></label>
      </aside>
    </section>

    <section v-if="step===2&&doc" class="review-layout">
      <div class="paper"><div class="section-heading"><div><h2>先核对，再分析</h2><p class="muted">{{doc.name}} · 版本 {{doc.version}}</p></div><span class="pill">{{length.toLocaleString()}} 字符</span></div>
        <p class="coverage">{{doc.coverage}}</p><ul class="warnings" v-if="doc.warnings.length"><li v-for="w in doc.warnings" :key="w">{{w}}</li></ul>
        <div class="edit-block" v-for="b in doc.blocks" :key="b.id"><label :for="b.id">{{b.location}}<span v-if="b.source==='user_revision'" class="revision">用户修订</span><span v-if="b.source==='ocr'" class="revision">OCR识别 · 请核对</span></label><textarea :id="b.id" v-model="edits[b.id]" :rows="Math.min(12,Math.max(3,b.text.split('\n').length+1))" @input="confirmed=false;consent=false;outbound=null"></textarea><details v-if="b.original_text"><summary>查看最初提取原文</summary><p class="prewrap">{{b.original_text}}</p></details></div>
        <button v-if="dirty" class="primary" @click="save" :disabled="(!!busy||toolBusy)">保存修订并生成新版本</button>
      </div>
      <aside class="paper analyze-panel"><h2>本次分析范围</h2><p>只分析左侧已提取或OCR识别的文字。未导入附件、未识别内容和图片含义不在分析范围内。</p><p class="muted">单次分析上限 {{health.max_analysis_chars.toLocaleString()}} 字符。超限会停止，不会截断。</p>
        <label class="check"><input type="checkbox" v-model="confirmed" :disabled="dirty"><span>我已核对正文与金额对应关系，了解上述覆盖范围。</span></label>
        <hr><label>运行方式<select v-model="mode"><option value="demo">演示模式（无模型分析）</option><option value="live" :disabled="!health.model_configured">真实模型分析{{health.model_configured?'':'（未配置）'}}</option></select></label>
        <p v-if="mode==='demo'" class="notice">演示仅展示报告布局与引用跳转，不会判断你的合同风险。</p>
        <template v-else><p class="muted">正文和背景将发送至后端配置的模型服务。系统会掩盖常见证件、账号、手机、邮箱和带标签姓名，但不能保证完全识别，请先手动清除其他敏感信息。</p><button @click="preview" :disabled="(!!busy||toolBusy)||dirty">预览脱敏正文</button><label class="check"><input type="checkbox" v-model="consent"><span>我同意发送脱敏正文及所填背景，用于本次合同阅读。</span></label></template>
        <button class="primary full" @click="run" :disabled="(!!busy||toolBusy)||dirty||!confirmed||length>health.max_analysis_chars||(mode==='live'&&!consent)">{{mode==='demo'?'查看演示报告':'生成合同阅读报告'}}</button>
        <p class="muted" v-if="dirty">请先保存修订，再确认分析范围。</p><p class="notice error" v-if="length>health.max_analysis_chars">正文超过分析上限，长合同分析尚未实现。</p>
        <details class="future"><summary>当前版本的能力边界</summary><p>上方工具支持销售承诺对照、退款试算、OCR、法规选编检索、版本比较和本机历史。OCR须核对，试算不等于最终退款；法规条文不自动适用。</p></details>
      </aside>
      <div v-if="outbound" class="paper outbound"><div class="section-heading"><h2>将发送的脱敏正文</h2><button @click="outbound=null">收起</button></div><p class="muted">背景字段也会应用相同脱敏规则。发送前请检查上一页背景中是否仍有个人信息。</p><p v-for="b in outbound.blocks" :key="b.id" class="prewrap"><strong>{{b.location}}</strong><br>{{b.text}}</p></div>
    </section>

    <section v-if="step===3&&result&&doc">
      <div :class="['report-banner',result.mode==='demo'?'demo':'live']"><strong>{{result.mode==='demo'?'演示报告 · 未分析合同':'AI 辅助阅读报告'}}</strong><span>{{result.evidence_status}}</span><button @click="step=2" :disabled="(!!busy||toolBusy)">返回核对正文</button></div>
      <div class="report-layout"><div class="report-main"><section class="paper report-summary"><h2>先看这几句话</h2><p>{{result.report.summary}}</p><small>{{result.coverage}} · 版本 {{result.version}}</small><p class="muted">{{result.scope_note}}</p><ul class="warnings"><li v-for="w in result.warnings" :key="w">{{w}}</li></ul></section>
      <section class="paper"><h2>合同里写了什么</h2><dl class="facts"><div v-for="f in result.report.facts" :key="f.label"><dt>{{factLabels[f.label] || f.label}}</dt><dd>{{f.value === '未发现明确约定' ? '这次提供的正文里，没找到明确说法' : f.value}}<button class="citation" v-for="e in f.evidence" :key="e.block_id+e.quote" @click="locate(e)">{{e.location}}</button></dd></div></dl></section>
      <section class="paper"><div class="section-heading"><h2>需要重点确认</h2><span>{{result.report.issues.length}} 项{{result.mode==='demo'?'布局示例':''}}</span></div><p v-if="!result.report.issues.length">在本次覆盖范围内未报告明显问题。这不代表合同不存在风险。</p>
        <article class="issue" v-for="(issue,i) in result.report.issues" :key="i"><div class="section-heading"><h3>{{issue.title}}</h3><span :class="['severity',issue.level==='高'?'high':issue.level==='中'?'medium':'low']">{{levelLabels[issue.level] || issue.level}}</span></div><p class="muted">{{issue.reason}} · {{statusLabels[issue.status] || issue.status}}</p><p><strong>这条在说什么：</strong>{{issue.explanation}}</p><p><strong>对你有什么影响：</strong>{{issue.impact}}</p><div class="ask"><p><strong>你可以直接这样问</strong><br>{{issue.question}}</p><p><strong>可以商量怎么改（需双方同意）</strong><br>{{issue.negotiation}}</p></div><p class="muted" v-if="issue.evidence.length">下面是合同原话，点击可以核对：</p><button class="quote" v-for="e in issue.evidence" :key="e.block_id+e.quote" @click="locate(e)"><q>{{e.quote}}</q><span>{{e.location}} · 定位原文</span></button></article>
      </section>
      <section class="paper"><h2>把问题说清楚</h2><ol class="questions"><li v-for="q in result.report.questions" :key="q">{{q}}</li></ol><h3>可以商量补进合同的内容（需双方同意）</h3><ul><li v-for="a in result.report.amendments" :key="a">{{a}}</li></ul><label>沟通草稿语气<select v-model="style" @change="adjust"><option>礼貌直接</option><option>简短询问</option><option>明确协商</option></select></label><textarea v-model="message" rows="7" aria-label="微信沟通草稿"></textarea><div class="actions"><small>可直接编辑。复制后由你自行决定是否发送。</small><button class="primary" @click="copy">复制微信草稿</button></div></section>
      <section class="paper"><h2>接下来可以做什么</h2><p class="muted">使用页面上方工具，把销售承诺与合同逐条对照，试算退款，查官方条文，比较修改版本。需要下次继续阅读，请手动保存到报告历史。</p></section></div>
      <aside class="paper source-panel"><h2>原文对照</h2><p class="muted">点击报告中的引用，可定位到这里。用户修订有独立标记。</p><article v-for="b in doc.blocks" :key="b.id" :id="'source-'+b.id" :class="['source-block',{highlighted:highlighted===b.id}]"><h3>{{b.location}} <span v-if="b.source==='user_revision'" class="revision">用户修订</span><span v-if="b.source==='ocr'" class="revision">OCR识别 · 请核对</span></h3><small class="block-id">{{b.id}}</small><p>{{b.text}}</p></article></aside></div>
      <div class="end-actions"><button @click="reset" :disabled="(!!busy||toolBusy)">清除本次文档与页面报告</button><small>未手动保存的报告刷新后会丢失。清除当前页面不会删除已保存的历史。</small></div>
    </section>
    <footer><span>明约 · 合同阅读工作台</span><span>合同文字解读与沟通建议，重要决定请结合完整材料人工复核。</span></footer>
  </main>
</template>
