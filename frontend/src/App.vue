<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import type { Document, Result, Evidence } from './types'
import ToolsPanel from './ToolsPanel.vue'
const ocrMode=ref('auto'), restoredTools=ref<any>(null), toolBusy=ref(false)
function restoreSnapshot(snapshot:any){setDoc(snapshot.document);if(snapshot.context)Object.assign(context,snapshot.context);result.value=snapshot.result;message.value=snapshot.draft||snapshot.result?.report.message||'';step.value=snapshot.result?3:2;nextTick(()=>restoredTools.value=snapshot.tools||{})}

const workflowPromises = ref('')
const workflowResult = computed(()=>(result.value as any)?.workflow)
const profile = ref<any>(null)
const ui = computed(()=>profile.value.ui)
const factLabels = computed<Record<string,string>>(()=>ui.value.fact_display)
const channel = ref('')
const statusLabels:Record<string,string> = {'明确约定':'合同写明了','表述含糊':'这里没说清楚','条款冲突':'前后说法不一致','信息缺失':'本次正文里没找到'}
const levelLabels:Record<string,string> = {'高':'优先问清楚','中':'建议问清楚','低':'了解一下'}
const step = ref(1), busy = ref(''), error = ref(''), toast = ref('')
const health = ref({model_configured:false,max_analysis_chars:24000})
const text = ref(''), doc = ref<Document|null>(null), result = ref<Result|null>(null)
const edits = reactive<Record<string,string>>({}), confirmed = ref(false), consent = ref(false)
const mode = ref<'demo'|'live'>('demo'), highlighted = ref(''), outbound = ref<Document|null>(null)
const message = ref(''), style = ref('礼貌直接')
watch(workflowPromises,()=>{consent.value=false})
function blankContext(){return {role:profile.value?.context.roles[0]??'',goal:profile.value?.context.goals[0]??'',signed:'未知',paid:'未知',amount:'',signed_date:'',paid_date:'',services:'',preferences:''}}
const context = reactive(blankContext())
const dirty = computed(()=>doc.value?.blocks.some(b=>edits[b.id] !== b.text) ?? false)
const length = computed(()=>doc.value?.blocks.reduce((n,b)=>n+b.text.length,0) ?? 0)

async function api<T>(path:string, options:RequestInit={}):Promise<T> {
  const response = await fetch('/api'+path, options)
  if(!response.ok) { const body = await response.json().catch(()=>({detail:'服务暂时不可用'})); throw new Error(body.detail || '请求失败') }
  return response.status===204 ? undefined as T : await response.json()
}
function json(method:string, body:unknown) {return {method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}}
async function work(label:string, fn:()=>Promise<void>) {if(busy.value||toolBusy.value)return;busy.value=label;error.value='';try{await fn()}catch(e){error.value=e instanceof Error?e.message:'操作失败，请重试'}finally{busy.value=''}}
function setDoc(value:Document){if(doc.value?.id!==value.id)workflowPromises.value='';restoredTools.value=null;doc.value=value;for(const key of Object.keys(edits))delete edits[key];for(const b of value.blocks)edits[b.id]=b.text;confirmed.value=false;consent.value=false;outbound.value=null;result.value=null;step.value=2}
async function importText(){await work('正在整理粘贴文本…', async()=>setDoc(await api<Document>('/documents/text',json('POST',{text:text.value}))))}
async function upload(event:Event){const input=event.target as HTMLInputElement;const file=input.files?.[0];if(!file)return;if(file.size>10*1024*1024){error.value='文件超过 10 MB 限制';input.value='';return}await work('正在提取正文和本机OCR，最长等待180秒…',async()=>setDoc(await api<Document>('/documents/upload?name='+encodeURIComponent(file.name)+'&ocr='+ocrMode.value,{method:'POST',body:file,headers:{'Content-Type':'application/octet-stream'}})));input.value=''}
function sample(){text.value=ui.value.sample}
async function save(){if(!doc.value)return;await work('正在保存正文修订…',async()=>setDoc(await api<Document>('/documents/'+doc.value!.id,json('PATCH',{version:doc.value!.version,edits}))))}
async function preview(){if(!doc.value)return;await work('正在生成脱敏预览…',async()=>{outbound.value=await api<Document>('/documents/'+doc.value!.id+'/outbound')})}
async function run(){if(!doc.value)return;await work(mode.value==='demo'?'正在生成演示布局…':'正在请求模型并校验引用，可能需要数分钟…',async()=>{result.value=await api<Result>('/workflow',json('POST',{document_id:doc.value!.id,version:doc.value!.version,mode:mode.value,context,consent:consent.value,confirmed:confirmed.value,promises:workflowPromises.value}));message.value=result.value.report.message;restoredTools.value={promises:workflowResult.value?.promises};step.value=3;window.scrollTo({top:0})})}
async function locate(e:Evidence){highlighted.value=e.block_id;await nextTick();document.getElementById('source-'+e.block_id)?.scrollIntoView({behavior:'smooth',block:'center'})}
async function copy(){try{await navigator.clipboard.writeText(message.value);toast.value='沟通草稿已复制';setTimeout(()=>toast.value='',2500)}catch{error.value='无法访问剪贴板，请选中草稿后手动复制。'}}
function adjust(){if(!result.value)return;const [briefStart,briefEnd]=ui.value.draft_brief,[askStart,askEnd]=ui.value.draft_negotiate;message.value=style.value==='简短询问'?briefStart+result.value.report.questions.slice(0,3).join(' ')+briefEnd:style.value==='明确协商'?askStart+result.value.report.questions.join('\n')+askEnd:result.value.report.message}
async function reset(){await work('正在清除临时文档…',async()=>{if(doc.value)await api('/documents/'+doc.value.id,{method:'DELETE'});doc.value=null;result.value=null;outbound.value=null;text.value='';message.value='';for(const key of Object.keys(edits))delete edits[key];Object.assign(context,blankContext());step.value=1})}
onMounted(()=>work('正在连接本地服务…',async()=>{profile.value=await api('/profile');Object.assign(context,blankContext());channel.value=ui.value.channels[0];health.value=await api('/health');mode.value=health.value.model_configured&&profile.value.ready.analysis?'live':'demo'}))
</script>

<template>
  <header class="topbar"><a class="brand" href="/" aria-label="明约首页"><span class="brand-icon">约</span><strong>明约</strong><span>合同理解与承诺核验智能体</span></a><span class="local"><i></i> 单用户本地工作台</span></header>
  <main v-if="!profile"><div v-if="error" class="notice error" role="alert">{{error}}</div><div v-else class="notice progress" role="status"><span class="spinner"></span>正在连接本地服务…</div></main>
  <main v-else>
    <div class="intro"><div><p class="audience">{{ui.audience}}</p><h1>先看清约定，<br class="mobile-break">再做决定。</h1><p>{{ui.intro}}</p></div><div class="intro-note"><span class="small-heading">openJiuwen SDK · 合同核验工作流</span><p><template v-for="(point,i) in ui.intro_points" :key="point"><template v-if="i"> <span>／</span> </template>{{point}}</template></p><small>{{ui.intro_disclaimer}}</small></div></div>
    <nav class="steps" aria-label="处理步骤"><button v-for="(label,index) in ['导入与背景','核对提取正文','阅读报告']" :key="label" :class="{active:step===index+1,done:step>index+1}" :disabled="(!!busy||toolBusy) || (index===1&&!doc) || (index===2&&!result)" @click="step=index+1"><span>{{index+1}}</span>{{label}}</button></nav>
    <div v-if="error" class="notice error" role="alert">{{error}}<button @click="error=''" aria-label="关闭提示">×</button></div>
    <div v-if="busy" class="notice progress" role="status"><span class="spinner"></span>{{busy}}</div>
    <div v-if="toast" class="toast" role="status">{{toast}}</div>

    <p v-if="dirty" class="notice">正文有尚未保存的修改，请先保存新版本，再使用合同工具。</p>
    <ToolsPanel :inert="!!busy||dirty" @busy="toolBusy=$event" :doc="doc" :result="result" :profile="profile" :restored-tools="restoredTools" :draft="message" @restore="restoreSnapshot" @import="step=1" />
    <section v-if="step===1" class="input-grid">
      <div class="paper"><div class="section-heading"><h2>导入你的合同</h2><span>PDF / DOCX / 图片 / 文本</span></div>
        <div v-if="doc" class="notice">已载入「{{doc.name}}」。<button :disabled="(!!busy||toolBusy)" @click="step=2">继续核对</button><button :disabled="(!!busy||toolBusy)" @click="reset">清除后重新导入</button></div>
        <template v-else><label>PDF文字提取方式<select v-model="ocrMode"><option value="auto">自动：缺少文字的页面做OCR</option><option value="force">整份OCR：适合混合页面或文字提取异常</option><option value="off">只提取已有文字，不做OCR</option></select></label><label class="upload"><span class="upload-icon">↥</span><strong>选择合同文件</strong><span>最大 10 MB，PDF 最多 80 页</span><small>支持扫描件和照片，本机OCR一次最多20页</small><input type="file" accept=".pdf,.docx,.png,.jpg,.jpeg,.webp" :disabled="(!!busy||toolBusy)" @change="upload"></label>
        <div class="or"><span>或者粘贴正文</span></div><label for="contract" class="sr-only">合同正文</label><textarea id="contract" v-model="text" rows="9" maxlength="250000" placeholder="把合同内容粘贴到这里，保留条款编号、金额和表格对应关系。"></textarea>
        <div class="actions"><button class="link-button" @click="sample" :disabled="(!!busy||toolBusy)">填入虚构示例</button><button class="primary" @click="importText" :disabled="!text.trim()||(!!busy||toolBusy)">提取并核对正文</button></div></template>
        <p class="privacy">原文件不落盘。未保存的正文在本机临时保留1小时；手动保存的历史保留到你主动删除。OCR在本机运行，调用模型前需另行确认。</p>
      </div>
      <aside class="paper background"><h2>补充你的情况</h2><p class="muted">不知道的可以留空，不会自动推断已签约或已使用服务。</p>
        <div class="form-row"><label>{{ui.context_labels.role}}<select v-model="context.role"><option v-for="r in profile.context.roles" :key="r">{{r}}</option></select></label><label>{{ui.context_labels.goal}}<select v-model="context.goal"><option v-for="g in profile.context.goals" :key="g">{{g}}</option></select></label></div>
        <div class="form-row"><label>{{ui.context_labels.signed}}<select v-model="context.signed"><option>未知</option><option>是</option><option>否</option></select></label><label>{{ui.context_labels.paid}}<select v-model="context.paid"><option>未知</option><option>是</option><option>否</option></select></label></div>
        <label>{{ui.context_labels.amount}}<input v-model="context.amount" inputmode="decimal" maxlength="40" placeholder="留空表示未知"></label>
        <div class="form-row"><label>{{ui.context_labels.signed_date}}<input type="date" v-model="context.signed_date"></label><label>{{ui.context_labels.paid_date}}<input type="date" v-model="context.paid_date"></label></div>
        <label>{{ui.context_labels.services}}<textarea v-model="context.services" maxlength="2000" rows="3" :placeholder="ui.context_placeholders.services"></textarea></label>
        <label>{{ui.context_labels.preferences}}<textarea v-model="context.preferences" maxlength="2000" rows="2" :placeholder="ui.context_placeholders.preferences"></textarea></label>
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
        <hr><label>{{ui.workflow_promise_label}}<textarea v-model="workflowPromises" rows="3" maxlength="6000" :placeholder="ui.workflow_promise_placeholder"></textarea></label><p class="muted">{{ui.task_plan}}</p><label>运行方式<select v-model="mode"><option value="demo">演示模式（无模型分析）</option><option value="live" :disabled="!health.model_configured||!profile.ready.analysis">真实模型分析{{!profile.ready.analysis?'（本地区尚未完成）':health.model_configured?'':'（未配置）'}}</option></select></label>
        <p v-if="mode==='demo'" class="notice">演示仅展示报告布局与引用跳转，不会判断你的合同风险。</p>
        <template v-else><p class="muted">正文和背景将发送至后端配置的模型服务。系统会掩盖常见证件、账号、手机、邮箱和带标签姓名，但不能保证完全识别，请先手动清除其他敏感信息。</p><button @click="preview" :disabled="(!!busy||toolBusy)||dirty">预览脱敏正文</button><label class="check"><input type="checkbox" v-model="consent"><span>{{ui.consent}}</span></label></template>
        <button class="primary full" @click="run" :disabled="(!!busy||toolBusy)||dirty||!confirmed||length>health.max_analysis_chars||(mode==='live'&&!consent)">{{mode==='demo'?'查看演示报告':'运行合同核验任务'}}</button>
        <p class="muted" v-if="dirty">请先保存修订，再确认分析范围。</p><p class="notice error" v-if="length>health.max_analysis_chars">正文超过分析上限，长合同分析尚未实现。</p>
        <details class="future"><summary>当前版本的能力边界</summary><p>{{ui.capabilities}}</p></details>
      </aside>
      <div v-if="outbound" class="paper outbound"><div class="section-heading"><h2>将发送的脱敏正文</h2><button @click="outbound=null">收起</button></div><p class="muted">背景字段也会应用相同脱敏规则。发送前请检查上一页背景中是否仍有个人信息。</p><p v-for="b in outbound.blocks" :key="b.id" class="prewrap"><strong>{{b.location}}</strong><br>{{b.text}}</p></div>
    </section>

    <section v-if="step===3&&result&&doc">
      <div :class="['report-banner',result.mode==='demo'?'demo':'live']"><strong>{{result.mode==='demo'?'演示报告 · 未分析合同':'AI 辅助阅读报告'}}</strong><span>{{result.evidence_status}}</span><button @click="step=2" :disabled="(!!busy||toolBusy)">返回核对正文</button></div>
      <section v-if="workflowResult" class="paper" style="margin-bottom:24px"><h2>本次任务执行记录</h2><p class="muted" v-if="workflowResult.engine">运行引擎：{{workflowResult.engine}} {{workflowResult.sdk_version}} · {{workflowResult.nodes.length}} 个工作流节点</p><p v-if="workflowResult.partial" class="notice error">部分步骤失败，已保留完成的报告。失败步骤可在上方工具中单独重试。</p><ol><li v-for="(item,i) in workflowResult.trace" :key="i"><strong>{{item.name}} · {{item.status}}</strong><p>{{item.detail}}</p></li></ol><details v-if="workflowResult.references.length"><summary>查看检索到的法规参考（不代表已经适用）</summary><article v-for="(law,i) in workflowResult.references" :key="i"><h3>{{law.title}} {{law.article}}</h3><p>{{law.text}}</p></article><p class="muted">仅为本机选编关键词检索；完整来源与版本请在“法规检索”工具中核对。</p></details></section><div class="report-layout"><div class="report-main"><section class="paper report-summary"><h2>先看这几句话</h2><p>{{result.report.summary}}</p><small>{{result.coverage}} · 版本 {{result.version}}</small><p class="muted">{{result.scope_note}}</p><ul class="warnings"><li v-for="w in result.warnings" :key="w">{{w}}</li></ul></section>
      <section class="paper"><h2>合同里写了什么</h2><dl class="facts"><div v-for="f in result.report.facts" :key="f.label"><dt>{{factLabels[f.label] || f.label}}</dt><dd>{{f.value === '未发现明确约定' ? '这次提供的正文里，没找到明确说法' : f.value}}<button class="citation" v-for="e in f.evidence" :key="e.block_id+e.quote" @click="locate(e)">{{e.location}}</button></dd></div></dl></section>
      <section class="paper"><div class="section-heading"><h2>需要重点确认</h2><span>{{result.report.issues.length}} 项{{result.mode==='demo'?'布局示例':''}}</span></div><p v-if="!result.report.issues.length">在本次覆盖范围内未报告明显问题。这不代表合同不存在风险。</p>
        <article class="issue" v-for="(issue,i) in result.report.issues" :key="i"><div class="section-heading"><h3>{{issue.title}}</h3><span :class="['severity',issue.level==='高'?'high':issue.level==='中'?'medium':'low']">{{levelLabels[issue.level] || issue.level}}</span></div><p class="muted">{{issue.reason}} · {{statusLabels[issue.status] || issue.status}}</p><p><strong>这条在说什么：</strong>{{issue.explanation}}</p><p><strong>对你有什么影响：</strong>{{issue.impact}}</p><div class="ask"><p><strong>你可以直接这样问</strong><br>{{issue.question}}</p><p><strong>可以商量怎么改（需双方同意）</strong><br>{{issue.negotiation}}</p></div><p class="muted" v-if="issue.evidence.length">下面是合同原话，点击可以核对：</p><button class="quote" v-for="e in issue.evidence" :key="e.block_id+e.quote" @click="locate(e)"><q>{{e.quote}}</q><span>{{e.location}} · 定位原文</span></button></article>
      </section>
      <section class="paper"><h2>把问题说清楚</h2><ol class="questions"><li v-for="q in result.report.questions" :key="q">{{q}}</li></ol><h3>可以商量补进合同的内容（需双方同意）</h3><ul><li v-for="a in result.report.amendments" :key="a">{{a}}</li></ul><label>沟通草稿语气<select v-model="style" @change="adjust"><option>礼貌直接</option><option>简短询问</option><option>明确协商</option></select></label><label v-if="ui.channels.length>1">发送渠道<select v-model="channel"><option v-for="c in ui.channels" :key="c">{{c}}</option></select></label><textarea v-model="message" rows="7" :aria-label="channel+'沟通草稿'"></textarea><div class="actions"><small>可直接编辑。复制后由你自行决定是否发送。</small><button class="primary" @click="copy">复制{{channel}}草稿</button></div></section>
      <section class="paper"><h2>接下来可以做什么</h2><p class="muted">{{ui.next_steps}}</p></section></div>
      <aside class="paper source-panel"><h2>原文对照</h2><p class="muted">点击报告中的引用，可定位到这里。用户修订有独立标记。</p><article v-for="b in doc.blocks" :key="b.id" :id="'source-'+b.id" :class="['source-block',{highlighted:highlighted===b.id}]"><h3>{{b.location}} <span v-if="b.source==='user_revision'" class="revision">用户修订</span><span v-if="b.source==='ocr'" class="revision">OCR识别 · 请核对</span></h3><small class="block-id">{{b.id}}</small><p>{{b.text}}</p></article></aside></div>
      <div class="end-actions"><button @click="reset" :disabled="(!!busy||toolBusy)">清除本次文档与页面报告</button><small>未手动保存的报告刷新后会丢失。清除当前页面不会删除已保存的历史。</small></div>
    </section>
    <footer><span>明约 · 合同阅读工作台</span><span>合同文字解读与沟通建议，重要决定请结合完整材料人工复核。</span></footer>
  </main>
</template>
