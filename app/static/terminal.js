'use strict';
const $=id=>document.getElementById(id);
const state={instruments:[],watch:[],selected:null,series:null,engineData:null,engines:{},meta:null,day:'',watchOnly:false,busy:false,updating:false,selectionId:0,loadId:0};
const drafts=new Map();
let noteDay=null;
const fmt=(n,d=2)=>n==null?'—':Number(n).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d});
const text=(tag,value,cls)=>{const el=document.createElement(tag);el.textContent=value;if(cls)el.className=cls;return el;};
function message(s){$('message').textContent=s;}
async function api(url,method='GET',body){
 const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});
 const result=await r.json();if(!r.ok)throw new Error(typeof result.detail==='string'?result.detail:'输入格式有误，请检查参数');return result;
}
function control(){for(const id of ['refresh','scan','csv-import','run-engine','save-notes'])$(id).disabled=state.busy||state.updating; if(state.meta?.simulated){$('refresh').disabled=true;$('scan').disabled=true;$('csv-import').disabled=true;}}
async function action(fn){if(state.busy)return;state.busy=true;control();try{await fn();}catch(e){message(e.message);}finally{state.busy=false;control();}}
function queryDay(){return state.day?'?day='+encodeURIComponent(state.day):'';}
function renderInstruments(){
 const box=$('instruments');box.replaceChildren();const search=$('search').value.trim().toLowerCase();
 const rows=state.instruments.filter(r=>(!state.watchOnly||state.watch.some(w=>w.code===r.code))&&`${r.code} ${r.name}`.toLowerCase().includes(search));
 $('pool-count').textContent=`${rows.length}只`;
 for(const row of rows){const button=text('button','',`instrument${row.code===state.selected?' active':''}`);button.append(text('span',row.name),text('span',fmt(row.close),'right'),text('small',`${row.code} · ${row.day}`));button.onclick=()=>selectStock(row.code).catch(e=>message(e.message));box.append(button);}
 if(!rows.length)box.append(text('div',state.watchOnly?'自选暂无已缓存行情。可从股票图表加入，或更新输入的研究股票池。':'没有匹配的缓存。先更新行情或导入CSV。','empty'));
}
function renderWatch(){const added=state.watch.some(w=>w.code===state.selected);$('watch-toggle').textContent=added?'★ 已自选 · 点击移除':'☆ 加入自选';$('watch-toggle').disabled=!state.selected;}
async function selectStock(code){
 const request=++state.selectionId;state.selected=code;renderInstruments();renderWatch();
 const data=await api('/api/series/'+encodeURIComponent(code)+queryDay());if(request!==state.selectionId)return;
 state.series=data;const last=data.points.at(-1),prev=data.points.at(-2);const change=prev?(last.close/prev.close-1)*100:null;
 $('stock-title').textContent=`${data.name} · ${data.code}`;
 $('stock-price').replaceChildren(text('span',fmt(last.close)),text('small',` 元  ${change==null?'':(change>=0?'+':'')+fmt(change)+'%'} · ${data.latest_day}`,change>=0?'up':'down'));
 $('chart-note').textContent=data.note+(data.latest_day!==data.as_of?' 所选日无行情，图表截至最近可用日。':'');
 const values=$('indicator-values');values.replaceChildren();
 for(const [label,value]of [['Wilder RSI(14)',last.rsi],['布林上轨(20,2)',last.upper],['布林下轨(20,2)',last.lower],['成交额（亿元）',last.amount/1e8]]){const el=text('div',label);el.append(text('b',fmt(value)));values.append(el);}
 drawCharts();
}
function points(){if(!state.series)return [];const n=Number($('range').value);return n?state.series.points.slice(-n):state.series.points;}
function canvasSetup(id){const canvas=$(id),rect=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=rect.width*dpr;canvas.height=rect.height*dpr;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);ctx.clearRect(0,0,rect.width,rect.height);return {canvas,ctx,w:rect.width,h:rect.height};}
function plot(id,rows,fields,colors,zero=false){
 const {ctx,w,h}=canvasSetup(id);const pad={left:12,right:58,top:15,bottom:25};const pw=w-pad.left-pad.right,ph=h-pad.top-pad.bottom;
 const values=rows.flatMap(r=>fields.map(f=>r[f])).filter(v=>v!=null&&Number.isFinite(v));if(!values.length){ctx.fillStyle='#91a2b9';ctx.fillText('暂无足够历史数据',15,40);return;}
 let min=Math.min(...values,...(zero?[0]:[])),max=Math.max(...values,...(zero?[0]:[]));const gap=(max-min)*.1||1;min-=gap;max+=gap;
 const x=i=>pad.left+i/Math.max(1,rows.length-1)*pw,y=v=>pad.top+(max-v)/(max-min)*ph;
 ctx.font='10px Segoe UI';ctx.lineWidth=1;ctx.strokeStyle='#263448';ctx.fillStyle='#7d91ab';
 for(let i=0;i<5;i++){const price=min+(max-min)*i/4;ctx.beginPath();ctx.moveTo(pad.left,y(price));ctx.lineTo(w-pad.right,y(price));ctx.stroke();ctx.fillText(price.toFixed(2),w-pad.right+6,y(price)+3);}
 if(rows.length){ctx.fillText(rows[0].day,pad.left,h-6);ctx.fillText(rows.at(-1).day,Math.max(pad.left,pad.left+pw-68),h-6);}
 if(zero)for(let i=0;i<rows.length;i++){const value=rows[i].histogram;if(value==null)continue;ctx.fillStyle=value>=0?'#d56d7a':'#4bbaa0';ctx.fillRect(x(i)-1,y(Math.max(0,value)),Math.max(1,Math.min(4,pw/rows.length*.6)),Math.max(1,Math.abs(y(value)-y(0))));}
 fields.forEach((field,index)=>{ctx.beginPath();ctx.strokeStyle=colors[index];ctx.lineWidth=field==='close'?1.8:1.1;let active=false;rows.forEach((row,i)=>{if(row[field]==null){active=false;return;}if(active)ctx.lineTo(x(i),y(row[field]));else ctx.moveTo(x(i),y(row[field]));active=true;});ctx.stroke();});
}
function drawCharts(){const rows=points();plot('price-chart',rows,['close','ma5','ma20','ma60'],['#79b0ff','#f7cc6c','#b298f4','#68dfba']);plot('macd-chart',rows,['dif','dea'],['#f7cc6c','#b298f4'],true);$('chart-day').textContent=rows.length?`${rows.length}期 · ${rows.at(-1).day}`:'暂无数据';}
$('price-chart').onpointermove=event=>{const rows=points();if(!rows.length)return;const rect=$('price-chart').getBoundingClientRect();const i=Math.round(Math.max(0,Math.min(1,(event.clientX-rect.left-12)/(rect.width-70)))*(rows.length-1));const r=rows[i];$('tooltip').hidden=false;$('tooltip').textContent=`${r.day}   收盘 ${fmt(r.close)}\nMA5 ${fmt(r.ma5)}  MA20 ${fmt(r.ma20)}  MA60 ${fmt(r.ma60)}\n成交额 ${fmt(r.amount/1e8)} 亿`;} ;
$('price-chart').onpointerleave=()=>{$('tooltip').hidden=true;};
new ResizeObserver(()=>drawCharts()).observe($('price-chart').parentElement);
$('range').onchange=drawCharts;
function engineInfo(){const info=state.engines[$('engine').value];if(!info)return;$('engine-description').textContent=info.description;$('engine-origin').textContent=info.origin;}
async function screenEngine(){
 engineInfo();
 const generation=++state.loadId;const engine=$('engine').value;if(!engine)return;
 const data=await api('/api/engine-screen?engine='+engine+(state.day?'&day='+state.day:''));if(generation!==state.loadId)return;
 state.engineData=data;$('match-count').textContent=`${data.items.length} / ${data.universe}`;const box=$('matches');box.replaceChildren();
 for(const row of data.items){const button=text('button','','match');const name=text('span',row.name);name.append(text('small',`${row.code} · ${row.verified?'状态已核验':'状态待核验'}`));button.append(name,text('b',fmt(row.score)+'分'));button.onclick=()=>selectStock(row.code).catch(e=>message(e.message));box.append(button);}
 if(!data.items.length)box.append(text('div',data.universe?'当前池没有命中。请查看淘汰原因；空结果不代表程序故障。':'还没有行情，请先更新或导入。','empty'));
 $('rejections').replaceChildren(...Object.entries(data.rejections).map(([key,value])=>text('p',`${key}：${value}只`)));
 $('daily-summary').textContent=`${data.day||'尚无行情'} · ${data.algorithm.name} · 池内${data.universe}只，命中${data.items.length}只。${data.note}`;
 await loadNotes(data.day);
}
async function loadNotes(day){noteDay=day;$('journal-date').textContent=day||'';$('journal-notes').value='';$('note-status').textContent='';if(!day)return;
 if(drafts.has(day)){$('journal-notes').value=drafts.get(day);$('note-status').textContent='本页未保存草稿';return;}
 try{const review=await api('/api/reviews/'+day);$('journal-notes').value=review.notes;$('note-status').textContent='已读取本日笔记';}catch(e){if(e.message!=='尚未生成复盘')throw e;}
}
async function load(){
 const [meta,instruments,watch,engines,days,report]=await Promise.all([api('/api/data-status'),api('/api/instruments'),api('/api/watchlist'),api('/api/engines'),api('/api/dates'),api('/api/dashboard')]);
 Object.assign(state,{meta,instruments,watch,engines});
 $('feed').textContent=meta.simulated?'模拟数据':!meta.latest_day?'真实行情待更新':meta.vendor==='local_csv'?'本地CSV · 待核验':meta.vendor==='tencent_fallback'?'腾讯备用 · 日线':'BaoStock · 日线';
 if(!$('pool').value)$('pool').value=(meta.sync?JSON.parse(meta.sync.codes):meta.default_codes).join(',');
 const old=$('engine').value;$('engine').replaceChildren();for(const [key,value]of Object.entries(engines)){const o=text('option',value.name);o.value=key;$('engine').append(o);}if(old in engines)$('engine').value=old;engineInfo();
 $('asof').replaceChildren();const latest=text('option','最新缓存日');latest.value='';$('asof').append(latest);for(const day of days){const o=text('option',day);o.value=day;$('asof').append(o);}if(days.includes(state.day))$('asof').value=state.day;else state.day='';
 const context=$('context');context.replaceChildren();
 for(const [name,value]of [['行情截至',meta.latest_day||'尚未同步'],['研究池覆盖',`${instruments.length}只 · 非全市场排名`],['数据口径',meta.simulated?'固定模拟样本':'日线 · 不复权'],['同步状态',meta.sync?new Date(meta.sync.updated_at).toLocaleString('zh-CN'):'等待首次更新']]){const item=text('div','');item.append(text('span',name),text('strong',value));context.append(item);}
 $('tasks').replaceChildren(...report.tasks.slice(0,6).map(t=>text('p',t)));if(!report.tasks.length)$('tasks').append(text('p','暂无新增待办。继续核对持仓风险与研究依据。'));
 if(meta.feed_note&&!report.tasks.includes(meta.feed_note))$('tasks').prepend(text('p',meta.feed_note));
 renderInstruments();renderWatch();await screenEngine();
 if(instruments.length){const code=instruments.some(r=>r.code===state.selected)?state.selected:instruments[0].code;await selectStock(code);}
 control();
}
async function poll(){try{const job=await api('/api/update-status');message(job.message);state.updating=job.state==='running';control();if(state.updating)setTimeout(poll,1500);else if(job.state==='done')await load();}catch(e){state.updating=false;control();message('更新状态读取失败：'+e.message);}}
async function update(market=false){
 const codes=[...new Set([...$('pool').value.split(/[,，\s]+/).filter(Boolean),...state.watch.map(w=>w.code)])];
 await api('/api/update','POST',{codes,feed:$('feed-choice').value,universe:market?'market':'custom'});state.updating=true;control();message('后台更新真实行情，原缓存仍可查看…');setTimeout(poll,800);
}
$('refresh').onclick=()=>action(()=>update());$('scan').onclick=()=>action(()=>update(true));
$('search').oninput=renderInstruments;
$('all-tab').onclick=()=>{state.watchOnly=false;$('all-tab').classList.add('selected');$('watch-tab').classList.remove('selected');renderInstruments();};
$('watch-tab').onclick=()=>{state.watchOnly=true;$('watch-tab').classList.add('selected');$('all-tab').classList.remove('selected');renderInstruments();};
$('watch-toggle').onclick=()=>action(async()=>{if(!state.selected)return;const exists=state.watch.some(w=>w.code===state.selected);state.watch=await api('/api/watchlist'+(exists?'/'+encodeURIComponent(state.selected):''),exists?'DELETE':'PUT',exists?undefined:{code:state.selected});renderWatch();renderInstruments();});
$('run-engine').onclick=()=>action(async()=>{await screenEngine();message('已按所选日期运行开源算法。仅筛选当前缓存池。');});
$('engine').onchange=()=>action(async()=>{engineInfo();await screenEngine();});
$('asof').onchange=()=>action(async()=>{state.day=$('asof').value;await screenEngine();if(state.selected)await selectStock(state.selected);});
$('journal-notes').oninput=()=>{if(noteDay)drafts.set(noteDay,$('journal-notes').value);$('note-status').textContent='未保存';};
window.addEventListener('beforeunload',event=>{if(drafts.size){event.preventDefault();event.returnValue='';}});
$('save-notes').onclick=()=>action(async()=>{const day=state.engineData?.day;if(!day)throw new Error('请先获取行情');const notes=$('journal-notes').value;await api('/api/reviews/'+day,'POST');await api('/api/reviews/'+day+'/notes','PUT',{notes});drafts.delete(day);$('note-status').textContent='笔记已保存至本机';message('本日研究笔记已保存，重启后保留。');});
$('csv-import').onclick=()=>action(async()=>{const file=$('csv-file').files[0];if(!file)throw new Error('请选择UTF-8 CSV文件');if(file.size>2000000)throw new Error('CSV文件不能超过2MB');if(!$('replace').checked)throw new Error('请确认用CSV替换当前行情缓存');const result=await api('/api/import-csv','POST',{text:await file.text(),replace_cache:true});$('replace').checked=false;await load();message(`已导入${result.imported}行CSV；价格来源由用户核验，未自动标记可交易状态。`);});
action(async()=>{await load();const job=await api('/api/update-status');if(job.state==='running'){state.updating=true;control();poll();}else message(state.meta.latest_day?'已读取本机缓存。可选择算法、查看走势，或更新真实行情。':'尚无真实行情。先输入研究股票池并更新；也可以导入自己的CSV。');});
