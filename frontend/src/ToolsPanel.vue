<script setup lang="ts">
import { ref, reactive, watch, onMounted, nextTick } from 'vue'
import type { Document, Result } from './types'
const props = defineProps<{doc:Document|null,result:Result|null,restoredTools?:any,draft?:string}>()
const emit = defineEmits<{restore:[snapshot:any],import:[],busy:[value:boolean]}>()
const panel = ref(''), busy = ref(''), error = ref(''), notice = ref('')
const promises = ref(''), promiseSource = ref(''), promiseConsent = ref(false), promiseResult = ref<any>(null)
const refundResult = ref<any>(null), comparison = ref<any>(null), legalResult = ref<any>(null)
const refundInput = reactive({paid:'',already_refunded:'0',services:[] as {name:string,quantity:string,unit_price:string,basis:string}[],penalty_base:'0',penalty_rate:'0',penalty_basis:'',confirmed:false})
const query = ref('退款'), historyItems = ref<any[]>([]), versions = ref<number[]>([]), left = ref(''), right = ref(''), otherDoc = ref<Document|null>(null)
const saveConsent = ref(false), deleteId = ref('')
watch(busy, value=>emit('busy',!!value))
async function api(path:string, method='GET', body?:unknown){const r=await fetch('/api'+path,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});if(!r.ok){const e=await r.json().catch(()=>({detail:'服务连接失败'}));throw new Error(e.detail)}return r.status===204?null:r.json()}
async function work(label:string, fn:()=>Promise<void>){if(busy.value)return;busy.value=label;error.value='';notice.value='';try{await fn()}catch(e){error.value=e instanceof Error?e.message:'操作失败'}finally{busy.value=''}}
function docRef(){return {document_id:props.doc!.id,version:props.doc!.version}}
async function loadHistory(){historyItems.value=await api('/history')}
async function open(name:string){panel.value=panel.value===name?'':name;await work('正在读取工具…',async()=>{if(name==='历史'||name==='版本'){await loadHistory();if(props.doc)versions.value=await api('/documents/'+props.doc.id+'/versions')}if(name==='法规'&&!legalResult.value)legalResult.value=await api('/legal/search?q='+encodeURIComponent(query.value))})}
async function promiseRun(){await work('正在逐条对照销售说法并核对引用…',async()=>{promiseResult.value=await api('/tools/promises','POST',{...docRef(),promises:promises.value,source:promiseSource.value||'用户提供的销售说法',consent:promiseConsent.value})})}
async function uploadText(event:Event, target:'promises'|'version'){
 const input=event.target as HTMLInputElement,file=input.files?.[0];if(!file)return
 await work('正在提取文件文字；扫描件会在本机OCR，最多等待180秒…',async()=>{if(file.size>10*1024*1024)throw new Error('文件不能超过10MB');const r=await fetch('/api/documents/upload?name='+encodeURIComponent(file.name),{method:'POST',body:file});const body=await r.json();if(!r.ok)throw new Error(body.detail);if(target==='promises'){promises.value=body.blocks.map((b:any)=>b.text).join('\n');promiseSource.value=file.name;promiseConsent.value=false;notice.value='已提取销售材料，请核对OCR文字，并整理为每行一条承诺后再对照。';await api('/documents/'+body.id,'DELETE')}else{otherDoc.value=body;right.value='other';notice.value='已载入另一版，请检查提取正文后比较。'}});input.value=''
}
async function calc(){await work('正在计算…',async()=>{refundResult.value=await api('/tools/refund'+(props.doc?'?document_id='+props.doc.id+'&version='+props.doc.version:''),'POST',refundInput)})}
function parseRef(value:string){if(value==='other'&&otherDoc.value)return {document_id:otherDoc.value.id,version:otherDoc.value.version};if(value.startsWith('v:'))return {document_id:props.doc!.id,version:Number(value.slice(2))};return {history_id:value.slice(2)}}
async function compare(){await work('正在逐句比较两个版本…',async()=>{comparison.value=await api('/tools/compare','POST',{left:parseRef(left.value),right:parseRef(right.value)})})}
async function search(){await work('正在检索官方条文选编…',async()=>{legalResult.value=await api('/legal/search?q='+encodeURIComponent(query.value))})}
async function refreshLaws(){await work('正在从官方来源更新条文…',async()=>{const status=await api('/legal/refresh','POST');legalResult.value=await api('/legal/search?q='+encodeURIComponent(query.value));notice.value=`条文库共 ${status.count} 条。各来源更新状态见下方。`})}
async function save(){await work('正在保存到本机…',async()=>{await api('/history','POST',{...docRef(),report_id:props.result?.report_id||null,draft:props.draft||''});await loadHistory();notice.value='已保存合同文字、当前报告和已完成的承诺对照/退款试算，可在历史记录恢复。';saveConsent.value=false})}
async function restore(id:string){await work('正在恢复历史记录…',async()=>{emit('restore',await api('/history/'+id+'/restore','POST'));notice.value='已恢复副本，原历史记录不会随修改而改变。'})}
async function remove(id:string){await work('正在删除历史记录…',async()=>{await api('/history/'+id,'DELETE');deleteId.value='';await loadHistory();notice.value='该条本机历史记录已删除。'})}
async function exportSnapshot(id:string){await work('正在导出…',async()=>{const snapshot=await api('/history/'+id);const url=URL.createObjectURL(new Blob([JSON.stringify(snapshot,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='合同阅读记录-'+id.slice(0,8)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)})}
function stamp(date:string){return new Date(date).toLocaleString('zh-CN')}
watch(()=>[props.doc?.id,props.doc?.version],([id],[oldId])=>{if(id!==oldId){promises.value='';promiseSource.value='';Object.assign(refundInput,{paid:'',already_refunded:'0',services:[],penalty_base:'0',penalty_rate:'0',penalty_basis:'',confirmed:false})}promiseResult.value=null;refundResult.value=null;comparison.value=null;versions.value=[];left.value='';right.value='';saveConsent.value=false;promiseConsent.value=false})
watch(()=>props.restoredTools,(value)=>{if(value?.promises){promises.value=value.promises.items.map((i:any)=>i.promise).join('\n');promiseSource.value=value.promises.source;nextTick(()=>promiseResult.value=value.promises)}else promiseResult.value=null;refundResult.value=value?.refund||null;if(value?.refund?.inputs){Object.assign(refundInput,value.refund.inputs,{confirmed:false});nextTick(()=>refundResult.value=value.refund)}},{deep:true})
watch([promises,promiseSource],()=>{promiseConsent.value=false;promiseResult.value=null})
watch(()=>JSON.stringify({...refundInput,confirmed:undefined}),()=>{refundResult.value=null;refundInput.confirmed=false})
onMounted(()=>loadHistory().catch(()=>{}))
</script>

<template>
 <section class="toolbox paper">
  <div class="section-heading"><div><h2>合同实用工具</h2><small>按需使用，结果可随报告保存到本机</small></div><span class="pill">六项工具</span></div>
  <nav class="tool-tabs" aria-label="合同实用工具"><button v-for="item in [['承诺','销售承诺对照'],['退款','退款试算'],['OCR','扫描件与图片'],['法规','法规检索'],['版本','版本比较'],['历史','报告历史']]" :key="item[0]" :class="{selected:panel===item[0]}" :disabled="!!busy" @click="open(item[0])">{{item[1]}}</button></nav>
  <div v-if="error" class="notice error" role="alert">{{error}}</div><div v-if="busy" class="notice progress" role="status">{{busy}}</div><p v-if="notice" class="notice" role="status">{{notice}}</p>

  <div v-if="panel==='承诺'" class="tool-body">
   <h3>销售说了什么，合同有没有写？</h3><p class="muted">每行一条。聊天截图可以先提取文字，再手动整理。这里只比较说法，不核实销售身份或截图真伪。</p>
   <p v-if="!doc" class="notice">请先导入并核对合同，再对照销售承诺。</p>
   <label>销售材料来源<input v-model="promiseSource" maxlength="200" placeholder="例如：10月20日销售微信聊天"></label>
   <label>导入聊天截图或销售材料<input type="file" accept=".png,.jpg,.jpeg,.webp,.pdf,.docx" :disabled="!!busy" @change="uploadText($event,'promises')"></label>
   <label>销售承诺（每行一条，最多30条）<textarea v-model="promises" maxlength="6000" rows="5" placeholder="例如：没找到工作就全额退费。请填写对方实际说过的话。"></textarea></label>
   <label class="check"><input v-model="promiseConsent" type="checkbox"><span>我已核对销售说法与当前合同，清除敏感信息，同意发送脱敏文字至已配置的模型服务。</span></label>
   <button class="primary" :disabled="!doc||!promiseConsent||!promises.trim()||!!busy" @click="promiseRun">逐条对照承诺</button>
   <div v-if="promiseResult"><p class="muted">{{promiseResult.note}}</p><article class="tool-result" v-for="row in promiseResult.items" :key="row.promise_id"><h3>{{row.promise_id}}. {{row.promise}}</h3><span class="pill">{{row.status}}</span><p>{{row.explanation}}</p><p class="ask">你可以这样问：{{row.question}}</p><blockquote v-for="e in row.evidence" :key="e.block_id+e.quote"><p>{{e.quote}}</p><small>{{e.location}}</small></blockquote></article></div>
  </div>

  <div v-if="panel==='退款'" class="tool-body">
   <h3>把扣费条件填清楚，再看能剩多少钱</h3><p class="muted">金额不自动猜。数量可填次数、月数、小时数；每项写明来自哪条约定或哪份服务记录。这里不判断扣费是否合法。</p>
   <div class="form-row"><label>实际付了多少钱（元）<input v-model="refundInput.paid" type="number" min="0" step="0.01"></label><label>已经退回多少钱（元）<input v-model="refundInput.already_refunded" type="number" min="0" step="0.01"></label></div>
   <article class="cost-row" v-for="(s,i) in refundInput.services" :key="i"><div class="form-row"><label>服务名称<input v-model="s.name" maxlength="100"></label><label>已用数量<input v-model="s.quantity" type="number" min="0" step="0.01"></label><label>每单位扣费（元）<input v-model="s.unit_price" type="number" min="0" step="0.01"></label></div><label>计算依据<input v-model="s.basis" maxlength="500" placeholder="例如：合同第5条；已完成2次辅导，有聊天记录"></label><button @click="refundInput.services.splice(i,1)">移除这一项</button></article>
   <button :disabled="refundInput.services.length>=50" @click="refundInput.services.push({name:'',quantity:'0',unit_price:'0',basis:''})">添加已用服务</button>
   <div class="form-row"><label>违约金按哪个金额算（元）<input v-model="refundInput.penalty_base" type="number" min="0" step="0.01"></label><label>违约金比例（%）<input v-model="refundInput.penalty_rate" type="number" min="0" max="100" step="0.01"></label></div><label>违约金的依据<input v-model="refundInput.penalty_basis" maxlength="500" placeholder="例如：合同第5.1条，按合同总额20%；不确定是否同时扣"></label>
   <label class="check"><input v-model="refundInput.confirmed" type="checkbox"><span>我已核对实付、已退、已用数量和扣费依据，知道这是条件试算。</span></label><button class="primary" @click="calc" :disabled="!!busy||!refundInput.paid||!refundInput.confirmed">计算两种情景</button>
   <div v-if="refundResult"><p class="notice">{{refundResult.note}}</p><div class="scenario-grid"><article class="tool-result" v-for="s in refundResult.scenarios" :key="s.title"><h3>{{s.title}}</h3><p class="amount">可能剩余 {{s.estimated_refund}} 元</p><p>实付 − 已退 − 已用服务 − 违约金</p><code>{{s.formula}}</code><p v-if="Number(s.excess_deductions)>0" class="notice">输入的扣费超出剩余款项 {{s.excess_deductions}} 元。这不代表你还欠这笔钱。</p></article></div><ul><li v-for="s in refundResult.services" :key="s.name">{{s.name}}：{{s.quantity}} × {{s.unit_price}} = {{s.subtotal}} 元；依据：{{s.basis}}</li></ul></div>
  </div>

  <div v-if="panel==='OCR'" class="tool-body"><h3>扫描合同、照片和聊天截图也可以导入</h3><p>支持 PDF、PNG、JPEG、WebP。本机识别文字后，仍由你先核对再分析。普通PDF自动提取文字，缺少文字的页面自动OCR；混合页面可以选“整份OCR”。</p><p class="muted">每个文件最多10MB，PDF最多80页，一次OCR最多20页。表格、手写字、金额和否定词可能识别错；印章和签名不做真伪判断。</p><button @click="emit('import')">去导入合同</button></div>

  <div v-if="panel==='法规'" class="tool-body"><h3>查官方原文，再判断是否适合自己的情况</h3><div class="search-row"><label>检索词<input v-model="query" maxlength="100" placeholder="退款、销售承诺、格式条款、违约金" @keyup.enter="search"></label><button class="primary" @click="search" :disabled="!!busy||!query.trim()">检索条文</button><button @click="refreshLaws" :disabled="!!busy">更新官方来源</button></div>
   <template v-if="legalResult"><p class="notice">{{legalResult.note}}</p><small>条文库 {{legalResult.count}} 条；匹配 {{legalResult.total_matches}} 条，最多展示15条。检索词只在本机检索，更新时仅请求下列官方页面。</small><details><summary>来源与更新状态</summary><p v-for="s in legalResult.sources" :key="s.url"><a :href="s.url" target="_blank" rel="noopener noreferrer">{{s.title}}</a> · {{s.count}}条 <span v-if="s.error"> · {{s.error}}</span></p></details><p v-if="!legalResult.results.length">没有匹配条文，可以换成“预付款”“解除”“格式条款”等词，或更新官方来源。</p><article class="tool-result" v-for="law in legalResult.results" :key="law.id"><h3>{{law.title}} · {{law.article}}</h3><small>{{law.edition}} · 该版本施行日期 {{law.effective}} · 获取时间 {{stamp(law.retrieved)}}</small><p class="prewrap">{{law.text}}</p><a :href="law.url" target="_blank" rel="noopener noreferrer">打开官方原文核对</a></article></template>
  </div>

  <div v-if="panel==='版本'" class="tool-body"><h3>看看前后两版改了什么</h3><p class="muted">可选本次修订版本、已保存的历史，或上传另一份合同。只比较文字，空格和换行会忽略。</p><label>上传另一版合同<input type="file" accept=".pdf,.docx,.png,.jpg,.jpeg,.webp" :disabled="!!busy" @change="uploadText($event,'version')"></label><details v-if="otherDoc"><summary>核对另一版提取正文：{{otherDoc.name}}</summary><p>{{otherDoc.coverage}}</p><p v-for="w in otherDoc.warnings" :key="w">{{w}}</p><p v-for="b in otherDoc.blocks" :key="b.id" class="prewrap"><strong>{{b.location}}</strong><br>{{b.text}}</p></details>
   <div class="form-row"><label v-for="side in ['left','right']" :key="side">{{side==='left'?'旧版':'新版'}}<select :value="side==='left'?left:right" @change="side==='left'?left=($event.target as HTMLSelectElement).value:right=($event.target as HTMLSelectElement).value"><option value="">请选择</option><option v-for="v in versions" :key="'v:'+v" :value="'v:'+v">当前合同 · 版本 {{v}}</option><option v-if="otherDoc" value="other">上传：{{otherDoc.name}}</option><option v-for="h in historyItems" :key="h.id" :value="'h:'+h.id">历史：{{h.name}} · {{stamp(h.created)}}</option></select></label></div><button class="primary" @click="compare" :disabled="!!busy||!left||!right||left===right">比较两个版本</button>
   <div v-if="comparison"><p class="notice">{{comparison.note}}</p><p>{{comparison.left.name}}（v{{comparison.left.version}}） → {{comparison.right.name}}（v{{comparison.right.version}}） · {{comparison.changes.length}}处改动</p><p v-if="!comparison.changes.length">提取文字一致（忽略空白后）。</p><article class="tool-result" v-for="(change,i) in comparison.changes" :key="i"><h3>{{Number(i)+1}}. {{change.kind}}</h3><div class="scenario-grid"><div class="diff-before"><strong>旧版</strong><p v-if="!change.before.length">（无）</p><p v-for="(part,j) in change.before" :key="j">{{part.text}}<br><small>{{part.location}}</small></p></div><div class="diff-after"><strong>新版</strong><p v-if="!change.after.length">（无）</p><p v-for="(part,j) in change.after" :key="j">{{part.text}}<br><small>{{part.location}}</small></p></div></div></article></div>
  </div>

  <div v-if="panel==='历史'" class="tool-body"><h3>保存下来，下次接着看</h3><p class="muted">手动保存后，合同正文、背景、报告和已完成的承诺对照/退款试算会写入本机项目 data/history.sqlite3。保存的是最近完成的对照和计算结果，不含尚未提交的输入修改。不会保存原始文件，也不上传云端。本机文件未加密，请妥善保管电脑。最多显示最近200条。</p><label class="check" v-if="doc"><input v-model="saveConsent" type="checkbox"><span>同意把当前合同和结果保存到本机，直到我主动删除。</span></label><button v-if="doc" class="primary" @click="save" :disabled="!!busy||!saveConsent">{{result?'保存当前报告与工具结果':'保存当前合同与工具结果'}}</button><p v-if="!historyItems.length">还没有保存记录。</p><article v-for="h in historyItems" :key="h.id" class="tool-result"><h3>{{h.name}}</h3><small>{{stamp(h.created)}}</small><div class="actions"><button @click="restore(h.id)" :disabled="!!busy">恢复阅读</button><button @click="exportSnapshot(h.id)" :disabled="!!busy">导出JSON备份</button><button @click="deleteId=h.id" :disabled="!!busy">删除</button></div><div v-if="deleteId===h.id" class="notice error">删除这条本机记录后，不能在应用内撤销。<button @click="remove(h.id)" :disabled="!!busy">确认删除这条记录</button><button @click="deleteId=''">取消</button></div></article></div>
 </section>
</template>

<style scoped>
.toolbox{margin-bottom:26px}.tool-tabs{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}.tool-tabs .selected{background:var(--ink);color:#fff}.tool-body{border-top:1px solid var(--line);margin-top:20px;padding-top:22px}.tool-result{border-top:1px solid var(--line);padding:20px 0;overflow-wrap:anywhere}.tool-result h3{margin-bottom:10px}.tool-result blockquote{margin:12px 0;background:#f2f7fa;border-left:3px solid #90b7c9;padding:12px 18px}.tool-result blockquote p{white-space:pre-wrap}.scenario-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.amount{font-size:24px;color:var(--ink);font-weight:700}.cost-row{background:#f3f7fa;padding:16px;margin-bottom:12px;border-radius:6px}.search-row{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap}.search-row label{flex:1;min-width:200px;margin:0}.diff-before,.diff-after{padding:16px;border-radius:5px;background:#fff2ef}.diff-after{background:#edf8f2}.diff-before p,.diff-after p{overflow-wrap:anywhere}a{color:#166b83}code{white-space:normal;overflow-wrap:anywhere}@media(max-width:650px){.scenario-grid{grid-template-columns:1fr}.tool-tabs button{flex:1 1 40%}}
</style>
