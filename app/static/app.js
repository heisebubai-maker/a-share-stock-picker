const $ = id => document.getElementById(id);
let busy = false, hasReview = false, metadata = null;
async function api(url, method='GET', body) {
  const response = await fetch(url, {method, headers: {'Content-Type':'application/json'}, ...(body ? {body:JSON.stringify(body)} : {})});
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '输入无效，请检查代码和日期');
  return value;
}
async function run(action) {
  if (busy) return;
  busy = true;
  ['screen','generate','save','day','sync','codes'].forEach(id => $(id).disabled = true);
  $('status').textContent = '正在处理，请稍候…';
  try { await action(); $('status').textContent = metadata?.simulated ? '已完成 · 模拟数据' : '已完成 · BaoStock缓存日线，非实时行情'; }
  catch (error) { $('status').textContent = error.message; }
  finally {
    busy = false;
    ['day','codes'].forEach(id => $(id).disabled = false);
    ['screen','generate'].forEach(id => $(id).disabled = !$('day').value);
    $('sync').disabled = !metadata || metadata.simulated;
    $('save').disabled = !hasReview;
  }
}
function cell(row, value) { const td = document.createElement('td'); td.textContent = value; row.append(td); }
async function loadReview() {
  hasReview = false; $('notes').value = ''; $('review').textContent = '尚未生成此日期复盘';
  try {
    const r = await api(`/api/reviews/${$('day').value}`);
    $('notes').value = r.notes; hasReview = true;
    $('review').textContent = `${r.summary.day} · ${r.summary.source} · ${r.summary.strategy} · 已保存 ${r.summary.items.length} 个候选的评分快照`;
  } catch (e) { if (e.message !== '尚未生成复盘') throw e; }
}
async function screen() {
  hasReview = false;
  $('rows').replaceChildren(); $('metrics').replaceChildren();
  const data = await api(`/api/screen?day=${$('day').value}`);
  for (const [name,value] of [['缓存股票数',data.universe],['当日缺失',data.missing],['通过筛选',data.eligible],['数据日期',data.day]]) {
    const div=document.createElement('div'); div.className='metric'; div.textContent=name;
    const strong=document.createElement('strong'); strong.textContent=value; div.append(strong); $('metrics').append(div);
  }
  for (const item of data.items) {
    const row=document.createElement('tr');
    [item.name+' / '+item.code,item.close.toFixed(2),item.score,item.momentum_pct+'%',Object.values(item.factors).join(' / ')].forEach(v=>cell(row,v));
    $('rows').append(row);
  }
  if (!data.items.length) { const row=document.createElement('tr'); cell(row,'没有合格股票：至少需要21期数据，且满足流动性与状态要求'); $('rows').append(row); }
  await loadReview();
}
async function refresh() {
  metadata = await api('/api/data-status');
  $('source').textContent = metadata.simulated ? '模拟数据' : metadata.latest_day ? 'BaoStock · 真实日线' : 'BaoStock · 待同步';
  $('notice').textContent = metadata.simulated ? '当前为虚构样本演示，不是真实行情。' : '当前为BaoStock日线缓存；不复权，除权除息可能影响评分。仅覆盖输入股票池，不是全市场排名。评分不代表盈利概率。';
  $('sync-panel').hidden = metadata.simulated;
  if (!$('codes').value) {
    const codes = metadata.sync ? JSON.parse(metadata.sync.codes) : metadata.default_codes;
    $('codes').value = codes.join(',');
  }
  $('freshness').textContent = metadata.latest_day ? `缓存最新日期：${metadata.latest_day}（距今天${metadata.age_days}个自然日，可能包含周末节假日） · 最近同步：${metadata.sync ? new Date(metadata.sync.updated_at).toLocaleString('zh-CN') : '无'}` : '尚未下载真实数据，请点击“同步真实数据”。';
  const days = await api('/api/dates');
  const previous = $('day').value;
  $('day').replaceChildren();
  for (const day of days) {const option=document.createElement('option'); option.value=day; option.textContent=day; $('day').append(option);}
  if (days.includes(previous)) $('day').value = previous;
  if (days.length) await screen();
  else { hasReview=false; $('rows').replaceChildren(); $('metrics').replaceChildren(); $('notes').value=''; $('review').textContent='同步真实日线后可生成复盘。'; }
}
$('screen').onclick=()=>run(screen);
$('day').onchange=()=>run(screen);
$('sync').onclick=()=>run(async()=>{
  const codes = $('codes').value.split(/[,，\s]+/).filter(Boolean);
  if (!codes.length || codes.length > 50) throw new Error('请输入1至50只股票代码');
  $('status').textContent='正在同步真实日线，最多等待约3分钟；失败后保留原缓存…';
  await api('/api/sync','POST',{codes}); await refresh();
});
$('generate').onclick=()=>run(async()=>{await api(`/api/reviews/${$('day').value}`,'POST'); await loadReview();});
$('save').onclick=()=>run(async()=>{await api(`/api/reviews/${$('day').value}/notes`,'PUT',{notes:$('notes').value}); await loadReview();});
run(refresh);
