const $ = id => document.getElementById(id);
let busy = false, hasReview = false;
async function api(url, method='GET', body) {
  const response = await fetch(url, {method, headers: {'Content-Type':'application/json'}, ...(body ? {body:JSON.stringify(body)} : {})});
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '输入无效');
  return value;
}
async function run(action) {
  if (busy) return;
  busy = true;
  ['screen','generate','save','day'].forEach(id => $(id).disabled = true);
  try { await action(); $('status').textContent = '已完成 · 所有结果均来自模拟样本'; }
  catch (error) { $('status').textContent = error.message; }
  finally { busy = false; ['screen','generate','day'].forEach(id => $(id).disabled = false); $('save').disabled = !hasReview; }
}
function cell(row, value) { const td = document.createElement('td'); td.textContent = value; row.append(td); }
async function loadReview() {
  hasReview = false; $('notes').value = ''; $('review').textContent = '尚未生成此日期复盘';
  try {
    const r = await api(`/api/reviews/${$('day').value}`);
    $('notes').value = r.notes; hasReview = true;
    $('review').textContent = `${r.summary.day} · 策略 ${r.summary.strategy} · 已保存 ${r.summary.items.length} 个候选样本的评分快照`;
  } catch (e) { if (e.message !== '尚未生成复盘') throw e; }
}
async function screen() {
  $('rows').replaceChildren(); $('metrics').replaceChildren();
  const data = await api(`/api/screen?day=${$('day').value}`);
  for (const [name,value] of [['样本总数',data.universe],['通过筛选',data.eligible],['数据日期',data.day]]) {
    const div=document.createElement('div'); div.className='metric'; div.textContent=name;
    const strong=document.createElement('strong'); strong.textContent=value; div.append(strong); $('metrics').append(div);
  }
  for (const item of data.items) {
    const row=document.createElement('tr');
    [item.name+' / '+item.code,item.close.toFixed(2),item.score,item.momentum_pct+'%',Object.values(item.factors).join(' / ')].forEach(v=>cell(row,v));
    $('rows').append(row);
  }
  if (!data.items.length) { const row=document.createElement('tr'); cell(row,'没有合格样本：需要至少21期数据'); $('rows').append(row); }
  await loadReview();
}
$('screen').onclick=()=>run(screen);
$('day').onchange=()=>run(screen);
$('generate').onclick=()=>run(async()=>{await api(`/api/reviews/${$('day').value}`,'POST'); await loadReview();});
$('save').onclick=()=>run(async()=>{await api(`/api/reviews/${$('day').value}/notes`,'PUT',{notes:$('notes').value}); await loadReview();});
run(async()=>{ const days=await api('/api/dates'); for(const day of days){const option=document.createElement('option'); option.value=day; option.textContent=day; $('day').append(option);} if(!days.length) throw new Error('暂无样本数据'); await screen(); });
