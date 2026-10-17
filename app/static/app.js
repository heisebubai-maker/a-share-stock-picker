const $=id=>document.getElementById(id);
let busy=false, updating=false, metadata=null, report=null, timer=null, hasReview=false;
const money=value=>value==null?'待补齐':Number(value).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
const pct=value=>value==null?'待补齐':`${Number(value).toFixed(2)}%`;
function el(tag,text,cls){const node=document.createElement(tag); if(text!=null)node.textContent=text;if(cls)node.className=cls;return node;}
function message(text){$('status').textContent=text;}
async function api(url,method='GET',body){
  const res=await fetch(url,{method,headers:{'Content-Type':'application/json'},...(body!==undefined?{body:JSON.stringify(body)}:{})});
  const data=await res.json();
  if(!res.ok)throw new Error(typeof data.detail==='string'?data.detail:(data.detail||[]).map(e=>e.msg).join('；')||'请求失败');
  return data;
}
function controls(){
  $('sync').disabled=busy||updating||metadata?.simulated;
  ['screen','generate'].forEach(id=>$(id).disabled=busy||!$('day').value);
  $('save').disabled=busy||!hasReview;
  $('save-report').disabled=busy||!report?.day;
}
async function run(action){if(busy)return;busy=true;controls();try{await action();}catch(e){message(e.message);}finally{busy=false;controls();}}
function metric(name,value,note){const box=el('div',null,'metric');box.append(el('span',name),el('strong',value),el('span',note));return box;}
function empty(target,text){target.replaceChildren(el('div',text,'empty'));}
function renderMarket(){
  const m=report.market;const box=$('market');box.replaceChildren();
  box.append(el('h3',`市场环境：${m.regime}`));
  if(m.indices.length){for(const index of m.indices)box.append(el('p',`${index.name} ${money(index.close)} · 日涨跌 ${pct(index.change_pct)} · ${index.close>=index.ma20?'位于':'低于'}20期均线（${money(index.ma20)}）`));}
  else box.append(el('p','尚无足够指数日线。更新行情后再判断环境，当前不形成新增仓位计划。'));
  box.append(el('p',`当前研究池 ${m.pool_size} 只，当日有数据 ${m.available} 只；具备足够历史的股票中上涨 ${m.up}、下跌 ${m.down}。`,'muted'));
  if(m.sectors.length)box.append(el('p','池内行业表现：'+m.sectors.slice(0,5).map(s=>`${s.name} ${pct(s.change_pct)}（${s.count}只）`).join(' · ')));
  box.append(el('p',m.note,'muted'));
  $('account').replaceChildren(metric('账户估算总资产',money(report.account.equity),'持仓市值 + 已录入现金'),metric('持仓账面盈亏',money(report.account.pnl),report.account.missing?'仅统计有行情持仓':'不含费用、分红与已实现收益'),metric('当前总仓位',pct(report.account.invested_pct),`设定上限 ${report.settings.max_total_pct}%`),metric('待补行情',String(report.account.missing),'不以旧价或模拟价补齐'));
  $('tasks').replaceChildren(...(report.tasks.length?report.tasks:['目前没有额外优先事项；按持仓风险线与候选条件继续观察。']).map(t=>el('li',t)));
}
function renderPicks(){
  const box=$('picks');box.replaceChildren();
  if(!report.candidates.length){empty(box,report.day?'当前没有符合条件的新候选。先处理已有持仓，不为凑数放宽规则。':'点击“一键更新行情与复盘”，再查看基于行情筛出的候选。');return;}
  for(const item of report.candidates){
    const card=el('article',null,'card');card.append(el('h3',`${item.name} · ${item.code}`),el('span',item.action,'tag'),el('p',`${money(item.close)} 元 · 评分 ${item.score.toFixed(1)} / 100`,'big'));
    card.append(el('p',`${item.sector||'行业未取得'} · PE(TTM) ${item.pe==null?'缺失':item.pe.toFixed(1)} · PB ${item.pb==null?'缺失':item.pb.toFixed(2)}`,'muted'));
    const reasons=el('ul');item.reasons.forEach(r=>reasons.append(el('li',r)));card.append(reasons);
    const p=item.plan;const plan=el('div',null,'plan');plan.append(el('p',`观察区 ${money(p.observation_low)}–${money(p.observation_high)} 元 · 失效线 ${money(p.invalidation)} 元`));
    const conditions=el('details');conditions.append(el('summary','查看触发条件与仓位方案'),el('p','观察区为最近收盘价±1%，不是限价委托建议。'),el('p',p.trigger),el('p',p.invalidation_rule),el('p',`新增股数上限：${p.shares_upper_bound} 股。${p.shares_upper_bound===0?'当前条件或账户参数不支持形成新增仓位。':''}`),el('p',p.sizing_note,'muted'));plan.append(conditions);
    card.append(plan);const risks=el('details');risks.append(el('summary','风险与缺少的依据'));item.risks.forEach(r=>risks.append(el('p',r)));card.append(risks);box.append(card);
  }
}
function editHolding(item){
  $('holding-form').hidden=false;$('h-code').value=item?.code||'';$('h-cost').value=item?.cost??'';$('h-quantity').value=item?.quantity??'';$('h-horizon').value=item?.horizon||'swing';$('h-thesis').value=item?.thesis||'';$('h-code').focus();
}
function renderHoldings(){
  const box=$('holdings');box.replaceChildren();
  if(!report.holdings.length){empty(box,'还没有持仓。点击“录入持仓”，填写代码、成本和数量；保存后，系统会告诉你哪些行情需要更新。');return;}
  for(const item of report.holdings){
    const card=el('article',null,'card');card.append(el('h3',`${item.name||item.code} · ${item.code}`),el('span',item.status,'tag '+(item.status==='趋势保持'?'':'warn')),el('p',item.action,'big'),el('p',`成本 ${money(item.cost)} 元 × ${item.quantity}股 · ${item.horizon==='long'?'中长期':'短线/波段'}`));
    if(item.value!=null)card.append(el('p',`收盘 ${money(item.close)} 元 · 盈亏 ${money(item.pnl)} 元（${pct(item.pnl_pct)}）`),el('p',`市值 ${money(item.value)} 元 · 账户仓位 ${pct(item.weight_pct)}`));
    card.append(el('p',item.reason,'muted'));
    if(item.thesis)card.append(el('p','我的持有逻辑：'+item.thesis));
    if(item.plan){const p=item.plan;const plan=el('div',null,'plan');plan.append(el('p',`成本风险线 ${money(p.risk_line)} 元 · 趋势参考 ${money(p.trend_line)} 元 · 收盘压力参考 ${money(p.review_level)} 元`),el('p',p.trigger),el('p',p.invalidation));card.append(plan);}
    const actions=el('div',null,'toolbar');const edit=el('button','修改持仓');edit.onclick=()=>editHolding(item);
    const remove=el('button','移除此持仓','danger');remove.onclick=()=>{if(window.confirm(`移除 ${item.code} 的当前持仓记录？已保存的每日复盘仍保留。`))run(async()=>{await api('/api/holdings/'+encodeURIComponent(item.code),'DELETE');await loadDashboard();message('持仓已移除，历史复盘仍保留。');});};
    actions.append(edit,remove);card.append(actions);box.append(card);
  }
}
async function loadDashboard(){
  report=await api('/api/dashboard');
  $('asof').textContent=report.day?`行情日期 ${report.day}${report.stale?' · 缓存较旧':''}`:'尚无行情';
  renderMarket();renderPicks();renderHoldings();
  const settings=report.settings;for(const [id,key]of [['s-cash','cash'],['s-stock','max_stock_pct'],['s-total','max_total_pct'],['s-loss','max_loss_pct'],['s-risk','risk_pct']])$(id).value=settings[key];
  $('limits').textContent=report.limitations.join(' ')+' 本地研究工具，不自动下单。';controls();
}
async function loadHistory(){
  const list=await api('/api/research-reports');const box=$('history');box.replaceChildren();
  if(!list.length){box.append(el('p','尚无保存的复盘。更新成功会自动保存，也可点击“保存本次复盘”。'));return;}
  for(const item of list){const button=el('button',`${item.day} · 查看快照`);button.onclick=()=>run(async()=>{const data=await api('/api/research-reports/'+item.day);$('history-detail').hidden=false;$('history-detail').textContent=[`${data.day}｜${data.source}｜${data.market.regime}`,'待办：',...data.tasks.map(t=>'• '+t),'持仓：',...data.holdings.map(h=>`${h.name||h.code}：${h.action}；盈亏 ${money(h.pnl)}；风险线 ${money(h.plan?.risk_line)}`),'候选：',...data.candidates.map(c=>`${c.name}：${c.action}；失效线 ${money(c.plan.invalidation)}`)].join('\n');});box.append(button);}
}
async function loadReview(){hasReview=false;$('notes').value='';$('review').textContent='尚未生成因子快照';if(!$('day').value)return;try{const r=await api('/api/reviews/'+$('day').value);$('notes').value=r.notes;hasReview=true;$('review').textContent=`${r.summary.day} · ${r.summary.items.length} 个合格结果`;}catch(e){if(e.message!=='尚未生成复盘')throw e;}}
async function screen(){if(!$('day').value)return;const data=await api('/api/screen?day='+$('day').value);$('rows').replaceChildren();for(const item of data.items){const row=el('tr');[item.name+' / '+item.code,money(item.close),item.score,pct(item.momentum_pct),Object.values(item.factors).join(' / ')].forEach(v=>row.append(el('td',v)));$('rows').append(row);}await loadReview();}
async function loadAll(){
  metadata=await api('/api/data-status');$('source').textContent=metadata.simulated?'模拟演示':metadata.latest_day?'BaoStock · 日线':'真实日线待更新';
  $('notice').textContent=metadata.simulated?'模拟模式：候选仅作交互演示，不估算真实持仓盈亏。':'使用不复权收盘价；除权可能影响趋势。行业为下载时快照，PE/PB不代表盈利质量。';
  $('freshness').textContent=metadata.latest_day?`缓存截至 ${metadata.latest_day}；最近同步 ${metadata.sync?new Date(metadata.sync.updated_at).toLocaleString('zh-CN'):'无'}。`:'暂无缓存。';
  if(!$('codes').value)$('codes').value=(metadata.sync?JSON.parse(metadata.sync.codes):metadata.default_codes).join(',');
  const days=await api('/api/dates');$('day').replaceChildren();for(const day of days){const option=el('option',day);option.value=day;$('day').append(option);}
  await loadDashboard();await loadHistory();await screen();
}
async function pollUpdate(){
  try{const state=await api('/api/update-status');updating=state.state==='running';message(state.message);controls();
    if(updating){timer=setTimeout(pollUpdate,1500);}
    else{timer=null;if(state.state==='done'){await loadAll();message('行情与复盘已更新，请先查看“下一步计划”。');}}
  }catch(e){updating=false;timer=null;message('读取更新状态失败，可刷新页面继续查看：'+e.message);controls();}
}
$('sync').onclick=()=>run(async()=>{const codes=$('codes').value.split(/[,，\s]+/).filter(Boolean);await api('/api/update','POST',{codes});updating=true;message('后台正在更新行情，你可以继续查看已有复盘。');if(!timer)timer=setTimeout(pollUpdate,1000);});
$('add-holding').onclick=()=>editHolding();$('cancel-holding').onclick=()=>{$('holding-form').hidden=true;};
$('holding-form').onsubmit=event=>{event.preventDefault();run(async()=>{await api('/api/holdings','PUT',{code:$('h-code').value,cost:Number($('h-cost').value),quantity:Number($('h-quantity').value),horizon:$('h-horizon').value,thesis:$('h-thesis').value});$('holding-form').hidden=true;await loadDashboard();message('持仓已保存；若提示行情缺失，点击“一键更新行情与复盘”。');});};
$('settings-form').onsubmit=event=>{event.preventDefault();run(async()=>{await api('/api/preferences','PUT',{cash:Number($('s-cash').value),max_stock_pct:Number($('s-stock').value),max_total_pct:Number($('s-total').value),max_loss_pct:Number($('s-loss').value),risk_pct:Number($('s-risk').value)});await loadDashboard();message('账户与研究参数已保存，计划已重算。');});};
$('save-report').onclick=()=>run(async()=>{await api('/api/research-reports','POST',{});await loadHistory();message('已保存本次行情、持仓和计划快照。');});
$('screen').onclick=()=>run(screen);$('day').onchange=()=>run(screen);
$('generate').onclick=()=>run(async()=>{await api('/api/reviews/'+$('day').value,'POST');await loadReview();message('因子快照已保存。');});
$('save').onclick=()=>run(async()=>{await api('/api/reviews/'+$('day').value+'/notes','PUT',{notes:$('notes').value});message('笔记已保存。');});
run(async()=>{await loadAll();const state=await api('/api/update-status');updating=state.state==='running';if(updating){message(state.message);timer=setTimeout(pollUpdate,1000);}else message('先看市场与持仓风险；需要新数据时点击右上角一键更新。');});
