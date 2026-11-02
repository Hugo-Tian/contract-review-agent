<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import type { Document, Result, Evidence } from './types'
import ToolsPanel from './ToolsPanel.vue'
import { t, lang, enabled, LANGS, type Lang } from './i18n'
const ocrMode=ref('auto'), restoredTools=ref<any>(null), toolBusy=ref(false)
function restoreSnapshot(snapshot:any){setDoc(snapshot.document);if(snapshot.context)Object.assign(context,snapshot.context);result.value=snapshot.result;message.value=snapshot.draft||snapshot.result?.report.message||'';step.value=snapshot.result?3:2;nextTick(()=>restoredTools.value=snapshot.tools||{})}

const workflowPromises = ref('')
const workflowResult = computed(()=>(result.value as any)?.workflow)
const profile = ref<any>(null)
const ui = computed(()=>profile.value.ui)
const factLabels = computed<Record<string,string>>(()=>ui.value.fact_display)
const channel = ref('')
const w = (s:string)=>s.replace(/合同/g, ui.value.doc_word)
const statusLabels:Record<string,string> = {'明确约定':'合同写明了','表述含糊':'这里没说清楚','条款冲突':'前后说法不一致','信息缺失':'本次正文里没找到'}
const levelLabels:Record<string,string> = {'高':'优先问清楚','中':'建议问清楚','低':'了解一下'}
const step = ref(1), busy = ref(''), error = ref(''), toast = ref('')
const health = ref({model_configured:false,max_analysis_chars:24000})
const text = ref(''), doc = ref<Document|null>(null), result = ref<Result|null>(null)
const edits = reactive<Record<string,string>>({}), confirmed = ref(false), consent = ref(false)
const mode = ref<'demo'|'live'>('demo'), highlighted = ref(''), outbound = ref<Document|null>(null)
const message = ref(''), style = ref('礼貌直接')
watch(workflowPromises,()=>{consent.value=false})
function blankContext(){const c=profile.value?.context;return {role:c?.roles[0]??'',goal:c?.goals[0]??'',signed:'未知',paid:'未知',amount:'',signed_date:'',paid_date:'',services:'',preferences:'',output_language:c?.languages[0]??'',channel:c?.channels[0]??'',recipient:c?.recipients[0]??''}}
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
async function run(){if(!doc.value)return;await work(mode.value==='demo'?'正在生成演示布局…':'正在请求模型并校验引用，可能需要数分钟…',async()=>{result.value=await api<Result>('/workflow',json('POST',{document_id:doc.value!.id,version:doc.value!.version,mode:mode.value,context,consent:consent.value,confirmed:confirmed.value,promises:workflowPromises.value}));message.value=result.value.report.message;channel.value=context.channel||ui.value.channels[0];restoredTools.value={promises:workflowResult.value?.promises};step.value=3;window.scrollTo({top:0})})}
async function locate(e:Evidence){highlighted.value=e.block_id;await nextTick();document.getElementById('source-'+e.block_id)?.scrollIntoView({behavior:'smooth',block:'center'})}
async function copy(){try{await navigator.clipboard.writeText(message.value);toast.value='沟通草稿已复制';setTimeout(()=>toast.value='',2500)}catch{error.value='无法访问剪贴板，请选中草稿后手动复制。'}}
function adjust(){if(!result.value)return;const [briefStart,briefEnd]=ui.value.draft_brief,[askStart,askEnd]=ui.value.draft_negotiate;message.value=style.value==='简短询问'?briefStart+result.value.report.questions.slice(0,3).join(' ')+briefEnd:style.value==='明确协商'?askStart+result.value.report.questions.join('\n')+askEnd:result.value.report.message}
async function reset(){await work('正在清除临时文档…',async()=>{if(doc.value)await api('/documents/'+doc.value.id,{method:'DELETE'});doc.value=null;result.value=null;outbound.value=null;text.value='';message.value='';for(const key of Object.keys(edits))delete edits[key];Object.assign(context,blankContext());followLanguage();step.value=1})}
onMounted(()=>work('正在连接本地服务…',async()=>{profile.value=await api('/profile');Object.assign(context,blankContext());enabled.value=profile.value.context.languages.length>0;followLanguage();channel.value=ui.value.channels[0];health.value=await api('/health');mode.value=health.value.model_configured&&profile.value.ready.analysis?'live':'demo'}))
// Switching the interface language also sets the report language; the two can still differ afterwards.
function followLanguage(){const report=LANGS.find(l=>l.value===lang.value)?.report;if(enabled.value&&report&&profile.value.context.languages.includes(report))context.output_language=report}
function setLang(value:Lang){lang.value=value;followLanguage()}
</script>

<template>
  <header class="topbar"><a class="brand" href="/" :aria-label="t('明约首页')"><span class="brand-icon">{{t('约')}}</span><strong>{{t('明约')}}</strong><span>{{t(w('合同理解与承诺核验智能体'))}}</span></a><span class="topbar-end"><span v-if="enabled" class="lang-switch" role="group" :aria-label="t('界面语言')"><button v-for="l in LANGS" :key="l.value" :class="{selected:lang===l.value}" :aria-pressed="lang===l.value" @click="setLang(l.value)">{{l.label}}</button></span><span class="local"><i></i> {{t('单用户本地工作台')}}</span></span></header>
  <main v-if="!profile"><div v-if="error" class="notice error" role="alert">{{t(error)}}</div><div v-else class="notice progress" role="status"><span class="spinner"></span>{{t('正在连接本地服务…')}}</div></main>
  <main v-else>
    <div class="intro"><div><p class="audience">{{t(ui.audience)}}</p><h1>{{t('先看清约定，')}}<br class="mobile-break">{{t('再做决定。')}}</h1><p>{{t(ui.intro)}}</p></div><div class="intro-note"><span class="small-heading">{{t(w('openJiuwen SDK · 合同核验工作流'))}}</span><p><template v-for="(point,i) in ui.intro_points" :key="point"><template v-if="i"> <span>／</span> </template>{{t(point)}}</template></p><small>{{t(ui.intro_disclaimer)}}</small></div></div>
    <nav class="steps" :aria-label="t('处理步骤')"><button v-for="(label,index) in ['导入与背景','核对提取正文','阅读报告']" :key="label" :class="{active:step===index+1,done:step>index+1}" :disabled="(!!busy||toolBusy) || (index===1&&!doc) || (index===2&&!result)" @click="step=index+1"><span>{{index+1}}</span>{{t(label)}}</button></nav>
    <div v-if="error" class="notice error" role="alert">{{t(error)}}<button @click="error=''" :aria-label="t('关闭提示')">×</button></div>
    <div v-if="busy" class="notice progress" role="status"><span class="spinner"></span>{{t(busy)}}</div>
    <div v-if="toast" class="toast" role="status">{{t(toast)}}</div>

    <p v-if="dirty" class="notice">{{t(w('正文有尚未保存的修改，请先保存新版本，再使用合同工具。'))}}</p>
    <ToolsPanel :inert="!!busy||dirty" @busy="toolBusy=$event" :doc="doc" :result="result" :profile="profile" :language="context.output_language" :restored-tools="restoredTools" :draft="message" @restore="restoreSnapshot" @import="step=1" />
    <section v-if="step===1" class="input-grid">
      <div class="paper"><div class="section-heading"><h2>{{t(w('导入你的合同'))}}</h2><span>{{t('PDF / DOCX / 图片 / 文本')}}</span></div>
        <div v-if="doc" class="notice">{{t('已载入「{name}」。',{name:doc.name})}}<button :disabled="(!!busy||toolBusy)" @click="step=2">{{t('继续核对')}}</button><button :disabled="(!!busy||toolBusy)" @click="reset">{{t('清除后重新导入')}}</button></div>
        <template v-else><label>{{t('PDF文字提取方式')}}<select v-model="ocrMode"><option value="auto">{{t('自动：缺少文字的页面做OCR')}}</option><option value="force">{{t('整份OCR：适合混合页面或文字提取异常')}}</option><option value="off">{{t('只提取已有文字，不做OCR')}}</option></select></label><label class="upload"><span class="upload-icon">↥</span><strong>{{t(w('选择合同文件'))}}</strong><span>{{t('最大 10 MB，PDF 最多 80 页')}}</span><small>{{t('支持扫描件和照片，本机OCR一次最多20页')}}</small><input type="file" accept=".pdf,.docx,.png,.jpg,.jpeg,.webp" :disabled="(!!busy||toolBusy)" @change="upload"></label>
        <div class="or"><span>{{t('或者粘贴正文')}}</span></div><label for="contract" class="sr-only">{{t(w('合同正文'))}}</label><textarea id="contract" v-model="text" rows="9" maxlength="250000" :placeholder="t(w('把合同内容粘贴到这里，保留条款编号、金额和表格对应关系。'))"></textarea>
        <div class="actions"><button class="link-button" @click="sample" :disabled="(!!busy||toolBusy)">{{t('填入虚构示例')}}</button><button class="primary" @click="importText" :disabled="!text.trim()||(!!busy||toolBusy)">{{t('提取并核对正文')}}</button></div></template>
        <p class="privacy">{{t('原文件不落盘。未保存的正文在本机临时保留1小时；手动保存的历史保留到你主动删除。OCR在本机运行，调用模型前需另行确认。')}}</p>
      </div>
      <aside class="paper background"><h2>{{t('补充你的情况')}}</h2><p class="muted">{{t('不知道的可以留空，不会自动推断已签约或已使用服务。')}}</p>
        <div class="form-row"><label>{{t(ui.context_labels.role)}}<select v-model="context.role"><option v-for="r in profile.context.roles" :key="r" :value="r">{{t(r)}}</option></select></label><label>{{t(ui.context_labels.goal)}}<select v-model="context.goal"><option v-for="g in profile.context.goals" :key="g" :value="g">{{t(g)}}</option></select></label></div>
        <div class="form-row"><label>{{t(ui.context_labels.signed)}}<select v-model="context.signed"><option value="未知">{{t('未知')}}</option><option value="是">{{t('是')}}</option><option value="否">{{t('否')}}</option></select></label><label>{{t(ui.context_labels.paid)}}<select v-model="context.paid"><option value="未知">{{t('未知')}}</option><option value="是">{{t('是')}}</option><option value="否">{{t('否')}}</option></select></label></div>
        <label>{{t(ui.context_labels.amount)}}<input v-model="context.amount" inputmode="decimal" maxlength="40" :placeholder="t('留空表示未知')"></label>
        <div class="form-row"><label>{{t(ui.context_labels.signed_date)}}<input type="date" v-model="context.signed_date"></label><label>{{t(ui.context_labels.paid_date)}}<input type="date" v-model="context.paid_date"></label></div>
        <label>{{t(ui.context_labels.services)}}<textarea v-model="context.services" maxlength="2000" rows="3" :placeholder="t(ui.context_placeholders.services)"></textarea></label>
        <label>{{t(ui.context_labels.preferences)}}<textarea v-model="context.preferences" maxlength="2000" rows="2" :placeholder="t(ui.context_placeholders.preferences)"></textarea></label>
        <div class="form-row" v-if="profile.context.languages.length"><label>{{t(ui.context_labels.output_language)}}<select v-model="context.output_language"><option v-for="l in profile.context.languages" :key="l">{{l}}</option></select></label><label>{{t(ui.context_labels.channel)}}<select v-model="context.channel"><option v-for="c in profile.context.channels" :key="c" :value="c">{{t(c)}}</option></select></label><label>{{t(ui.context_labels.recipient)}}<select v-model="context.recipient"><option v-for="r in profile.context.recipients" :key="r" :value="r">{{t(r)}}</option></select></label></div>
      </aside>
    </section>

    <section v-if="step===2&&doc" class="review-layout">
      <div class="paper"><div class="section-heading"><div><h2>{{t('先核对，再分析')}}</h2><p class="muted">{{doc.name}} · {{t('版本 {n}',{n:doc.version})}}</p></div><span class="pill">{{t('{n} 字符',{n:length.toLocaleString()})}}</span></div>
        <p class="coverage">{{t(doc.coverage)}}</p><ul class="warnings" v-if="doc.warnings.length"><li v-for="w in doc.warnings" :key="w">{{t(w)}}</li></ul>
        <div class="edit-block" v-for="b in doc.blocks" :key="b.id"><label :for="b.id">{{t(b.location)}}<span v-if="b.source==='user_revision'" class="revision">{{t('用户修订')}}</span><span v-if="b.source==='ocr'" class="revision">{{t('OCR识别 · 请核对')}}</span></label><textarea :id="b.id" v-model="edits[b.id]" :rows="Math.min(12,Math.max(3,b.text.split('\n').length+1))" @input="confirmed=false;consent=false;outbound=null"></textarea><details v-if="b.original_text"><summary>{{t('查看最初提取原文')}}</summary><p class="prewrap">{{b.original_text}}</p></details></div>
        <button v-if="dirty" class="primary" @click="save" :disabled="(!!busy||toolBusy)">{{t('保存修订并生成新版本')}}</button>
      </div>
      <aside class="paper analyze-panel"><h2>{{t('本次分析范围')}}</h2><p>{{t('只分析左侧已提取或OCR识别的文字。未导入附件、未识别内容和图片含义不在分析范围内。')}}</p><p class="muted">{{t('单次分析上限 {n} 字符。超限会停止，不会截断。',{n:health.max_analysis_chars.toLocaleString()})}}</p>
        <label class="check"><input type="checkbox" v-model="confirmed" :disabled="dirty"><span>{{t('我已核对正文与金额对应关系，了解上述覆盖范围。')}}</span></label>
        <hr><label>{{t(ui.workflow_promise_label)}}<textarea v-model="workflowPromises" rows="3" maxlength="6000" :placeholder="t(ui.workflow_promise_placeholder)"></textarea></label><p class="muted">{{t(ui.task_plan)}}</p><label>{{t('运行方式')}}<select v-model="mode"><option value="demo">{{t('演示模式（无模型分析）')}}</option><option value="live" :disabled="!health.model_configured||!profile.ready.analysis">{{t('真实模型分析')}}{{t(!profile.ready.analysis?'（本地区尚未完成）':health.model_configured?'':'（未配置）')}}</option></select></label>
        <p v-if="mode==='demo'" class="notice">{{t(w('演示仅展示报告布局与引用跳转，不会判断你的合同风险。'))}}</p>
        <template v-else><p class="muted">{{t('正文和背景将发送至后端配置的模型服务。系统会掩盖常见证件、账号、手机、邮箱和带标签姓名，但不能保证完全识别，请先手动清除其他敏感信息。')}}</p><button @click="preview" :disabled="(!!busy||toolBusy)||dirty">{{t('预览脱敏正文')}}</button><p v-if="ui.outbound_warning" class="notice">{{t(ui.outbound_warning)}}</p><label class="check"><input type="checkbox" v-model="consent"><span>{{t(ui.consent)}}</span></label></template>
        <button class="primary full" @click="run" :disabled="(!!busy||toolBusy)||dirty||!confirmed||length>health.max_analysis_chars||(mode==='live'&&!consent)">{{t(w(mode==='demo'?'查看演示报告':'运行合同核验任务'))}}</button>
        <p class="muted" v-if="dirty">{{t('请先保存修订，再确认分析范围。')}}</p><p class="notice error" v-if="length>health.max_analysis_chars">{{t(w('正文超过分析上限，长合同分析尚未实现。'))}}</p>
        <details class="future"><summary>{{t('当前版本的能力边界')}}</summary><p>{{t(ui.capabilities)}}</p></details>
      </aside>
      <div v-if="outbound" class="paper outbound"><div class="section-heading"><h2>{{t('将发送的脱敏正文')}}</h2><button @click="outbound=null">{{t('收起')}}</button></div><p v-if="ui.outbound_warning" class="notice">{{t(ui.outbound_warning)}}</p><p class="muted">{{t('背景字段也会应用相同脱敏规则。发送前请检查上一页背景中是否仍有个人信息。')}}</p><p v-for="b in outbound.blocks" :key="b.id" class="prewrap"><strong>{{t(b.location)}}</strong><br>{{b.text}}</p></div>
    </section>

    <section v-if="step===3&&result&&doc">
      <div :class="['report-banner',result.mode==='demo'?'demo':'live']"><strong>{{t(w(result.mode==='demo'?'演示报告 · 未分析合同':'AI 辅助阅读报告'))}}</strong><span>{{t(result.evidence_status)}}</span><button @click="step=2" :disabled="(!!busy||toolBusy)">{{t('返回核对正文')}}</button></div>
      <section v-if="workflowResult" class="paper" style="margin-bottom:24px"><h2>{{t('本次任务执行记录')}}</h2><p class="muted" v-if="workflowResult.engine">{{t('运行引擎：{engine} {version} · {n} 个工作流节点',{engine:workflowResult.engine,version:workflowResult.sdk_version,n:workflowResult.nodes.length})}}</p><p v-if="workflowResult.partial" class="notice error">{{t('部分步骤失败，已保留完成的报告。失败步骤可在上方工具中单独重试。')}}</p><ol><li v-for="(item,i) in workflowResult.trace" :key="i"><strong>{{t(item.name)}} · {{t(item.status)}}</strong><p>{{t(item.detail)}}</p></li></ol><details v-if="workflowResult.references.length"><summary>{{t('查看检索到的法规参考（不代表已经适用）')}}</summary><article v-for="(law,i) in workflowResult.references" :key="i"><h3>{{law.title}} {{law.article}}</h3><p>{{law.text}}</p></article><p class="muted">{{t('仅为本机选编关键词检索；完整来源与版本请在“法规检索”工具中核对。')}}</p></details></section><div class="report-layout"><div class="report-main"><section class="paper report-summary"><h2>{{t('先看这几句话')}}</h2><p>{{result.report.summary}}</p><small>{{t(result.coverage)}} · {{t('版本 {n}',{n:result.version})}}</small><p class="muted">{{t(result.scope_note)}}</p><ul class="warnings"><li v-for="w in result.warnings" :key="w">{{t(w)}}</li></ul></section>
      <section class="paper"><h2>{{t(w('合同里写了什么'))}}</h2><dl class="facts"><div v-for="f in result.report.facts" :key="f.label"><dt>{{t(factLabels[f.label] || f.label)}}</dt><dd>{{f.value === '未发现明确约定' ? t('这次提供的正文里，没找到明确说法') : f.value}}<button class="citation" v-for="e in f.evidence" :key="e.block_id+e.quote" @click="locate(e)">{{e.location}}</button></dd></div></dl></section>
      <section class="paper"><div class="section-heading"><h2>{{t('需要重点确认')}}</h2><span>{{t('{n} 项',{n:result.report.issues.length})}}{{result.mode==='demo'?t('布局示例'):''}}</span></div><p v-if="!result.report.issues.length">{{t(w('在本次覆盖范围内未报告明显问题。这不代表合同不存在风险。'))}}</p>
        <article class="issue" v-for="(issue,i) in result.report.issues" :key="i"><div class="section-heading"><h3>{{issue.title}}</h3><span :class="['severity',issue.level==='高'?'high':issue.level==='中'?'medium':'low']">{{t(levelLabels[issue.level] || issue.level)}}</span></div><p class="muted">{{issue.reason}} · {{t(w(statusLabels[issue.status] || issue.status))}}</p><p><strong>{{t('这条在说什么：')}}</strong>{{issue.explanation}}</p><p><strong>{{t('对你有什么影响：')}}</strong>{{issue.impact}}</p><div class="ask"><p><strong>{{t('你可以直接这样问')}}</strong><br>{{issue.question}}</p><p><strong>{{t('可以商量怎么改（需双方同意）')}}</strong><br>{{issue.negotiation}}</p></div><p class="muted" v-if="issue.evidence.length">{{t(w('下面是合同原话，点击可以核对：'))}}</p><button class="quote" v-for="e in issue.evidence" :key="e.block_id+e.quote" @click="locate(e)"><q>{{e.quote}}</q><span>{{t(e.location)}} · {{t('定位原文')}}</span></button></article>
      </section>
      <section class="paper"><h2>{{t('把问题说清楚')}}</h2><ol class="questions"><li v-for="q in result.report.questions" :key="q">{{q}}</li></ol><h3>{{t(w('可以商量补进合同的内容（需双方同意）'))}}</h3><ul><li v-for="a in result.report.amendments" :key="a">{{a}}</li></ul><label>{{t('沟通草稿语气')}}<select v-model="style" @change="adjust"><option value="礼貌直接">{{t('礼貌直接')}}</option><option value="简短询问">{{t('简短询问')}}</option><option value="明确协商">{{t('明确协商')}}</option></select></label><label v-if="ui.channels.length>1">{{t('发送渠道')}}<select v-model="channel"><option v-for="c in ui.channels" :key="c" :value="c">{{t(c)}}</option></select></label><textarea v-model="message" rows="7" :aria-label="channel+'沟通草稿'"></textarea><div class="actions"><small>{{t('可直接编辑。复制后由你自行决定是否发送。')}}</small><button class="primary" @click="copy">{{t('复制{channel}草稿',{channel:t(channel)})}}</button></div></section>
      <section class="paper"><h2>{{t('接下来可以做什么')}}</h2><p class="muted">{{t(ui.next_steps)}}</p></section></div>
      <aside class="paper source-panel"><h2>{{t('原文对照')}}</h2><p class="muted">{{t('点击报告中的引用，可定位到这里。用户修订有独立标记。')}}</p><article v-for="b in doc.blocks" :key="b.id" :id="'source-'+b.id" :class="['source-block',{highlighted:highlighted===b.id}]"><h3>{{t(b.location)}} <span v-if="b.source==='user_revision'" class="revision">{{t('用户修订')}}</span><span v-if="b.source==='ocr'" class="revision">{{t('OCR识别 · 请核对')}}</span></h3><small class="block-id">{{b.id}}</small><p>{{b.text}}</p></article></aside></div>
      <div class="end-actions"><button @click="reset" :disabled="(!!busy||toolBusy)">{{t('清除本次文档与页面报告')}}</button><small>{{t('未手动保存的报告刷新后会丢失。清除当前页面不会删除已保存的历史。')}}</small></div>
    </section>
    <section v-if="ui.help_links?.length" class="paper help-links"><h2>{{t('遇到租房问题，可以找谁')}}</h2><ul><li v-for="link in ui.help_links" :key="link.url"><a :href="link.url" target="_blank" rel="noopener noreferrer">{{t(link.name)}}</a><span>{{t(link.scope)}}</span></li></ul><p class="muted">{{t(ui.help_note)}}</p></section>
    <footer><span>{{t(w('明约 · 合同阅读工作台'))}}</span><span>{{t(ui.footer_note)}}</span></footer>
  </main>
</template>
