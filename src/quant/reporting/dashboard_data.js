/* Local data inventory and explicit, guarded synchronization. */
(() => {
  const el = id => document.getElementById(id);
  const escape = x => String(x ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const names = {futu:'Futu',tdx:'通达信',tushare:'Tushare',yahoo:'Yahoo',akshare:'AKShare',akshare_sina:'AKShare · 新浪',akshare_eastmoney:'AKShare · 东财'};
  const taskNames = {'QuantitativeTrading-BaostockHistory':'BaoStock 全市场 5 分钟','QuantitativeTrading-MinutesRecent':'全市场近期分钟','QuantitativeTrading-MinutesHistory':'Futu 长期历史','QuantitativeTrading-DailyObservation':'原有日更','QuantitativeTrading-RealtimeQuotes':'盘中行情'};
  const states = {Running:'运行中',Ready:'待机',Disabled:'已停用',Missing:'未安装',requested:'已提交',already_running:'已在运行',error:'未能启动'};
  let inventory = {}, page = 0, loading = false, tasksLoading = false;
  function filtered() {
    const term = el('minuteSearch').value.trim().toLowerCase(), scope = el('minuteScope').value;
    return (inventory.minute_symbols || []).filter(r => (!term || [r.symbol,r.name,...r.sources].join(' ').toLowerCase().includes(term)) &&
      (scope !== 'complete' || r.plan_years_complete) && (scope !== 'pending' || !r.plan_years_complete) &&
      (scope !== 'universe' || r.in_universe));
  }
  function drawList() {
    const rows = filtered(), size = 20;
    page = Math.min(page, Math.max(0, Math.ceil(rows.length/size)-1));
    el('minuteCount').textContent = `${rows.length.toLocaleString()} 个匹配标的 · 第 ${page+1} / ${Math.max(1,Math.ceil(rows.length/size))} 页`;
    el('minutePrev').disabled = page === 0; el('minuteNext').disabled = (page+1)*size >= rows.length;
    el('minuteRows').innerHTML = rows.slice(page*size,(page+1)*size).map(r => `<tr><td>${escape(r.symbol)}<br><small>${escape(r.name || (r.in_universe?'':'当前股票/ETF名单外'))}</small></td><td>${escape(r.sources.map(x=>names[x]||x).join(' / '))}</td><td>${escape(r.first)}<br>至 ${escape(r.last)}</td><td>${escape(r.earliest_available || '尚未探测')}</td><td>${escape(r.years.join('、') || '暂无 Futu 年度分区')}</td><td>${r.plan_years_complete?'计划年份已齐':r.earliest_available?'待补 '+escape(r.missing_years.join('、')):'待探测历史起点'}<br><small>${r.latest_reached?'最新日期已达到 '+escape(r.target_end):'最新日期待补'} · 逐日完整性未核验</small></td></tr>`).join('') || '<tr><td colspan="6">暂无匹配标的；可调整筛选或等待首次统计完成。</td></tr>';
  }
  function render() {
    const scan = inventory.scan || {}, c = inventory.collection || {}, r = c.recent || {}, h = c.history || {}, quota = h.quota_after || h.quota_before;
    el('dataStamp').textContent = `${inventory.updated_at?'统计时间 '+inventory.updated_at:'尚无覆盖快照'}${scan.running?' · 扫描中 '+scan.scanned+'/'+scan.total:''}${scan.error?' · 扫描失败 '+scan.error:''}`;
    el('dataSummary').textContent = inventory.has_snapshot ? `当前股票/ETF名单 ${inventory.universe_total.toLocaleString()} 只 · 已存 1 分钟 ${inventory.stored_minute_universe.toLocaleString()} 只 · Futu 计划年份已齐 ${inventory.plan_years_complete.toLocaleString()} 只` : '正在读取本地行情文件；首次统计完成前不显示零覆盖结论。';
    const order = {'1m':1,'5m':5,'15m':15,'30m':30,'60m':60,'1d':1440};
    const rows = [...(inventory.overview || [])].sort((a,b)=>(order[a.frequency]||9999)-(order[b.frequency]||9999)||a.source.localeCompare(b.source));
    el('dataCoverage').innerHTML = rows.map(r=>`<tr><td>${escape(r.frequency==='1d'?'日线':r.frequency.replace('m',' 分钟'))}</td><td>${escape(names[r.source]||r.source)}</td><td>${escape(r.first)}</td><td>${escape(r.last)}</td><td>${r.symbols.toLocaleString()}</td><td>${r.files.toLocaleString()}</td></tr>`).join('') || '<tr><td colspan="6">覆盖统计尚未生成</td></tr>';
    const absent = ['1m','5m','15m','30m','60m','1d'].filter(f=>!rows.some(r=>r.frequency===f));
    el('dataLimits').textContent = (inventory.coverage_note || '日期范围是已存记录边界，不代表连续完整。') + (inventory.has_snapshot&&absent.length?' 当前未发现独立存储：'+absent.join('、')+'。':'') + ((inventory.errors||[]).length?' 有 '+inventory.errors.length+' 个文件读取失败，统计可能不完整。':'');
    const runStates={running:'采集中',completed:'本轮结束',failed:'采集失败',paused:'已暂停'};
    el('dataProgress').textContent = `近期分钟：${runStates[r.status]||r.status||'状态未知'}，${r.completed??'—'} / ${r.universe_total??r.total??'—'} 标的，本轮新增/修订 ${r.changed_rows??'—'} 行；历史：${runStates[h.status]||h.status||'状态未知'}，本轮已保存 ${h.saved_partitions_this_run??0} 个年度分区${quota?'，额度已用 '+quota.used+' / 剩余 '+quota.remaining:''}${h.pause_reason?'，暂停原因 '+({quota_or_daily_budget:'额度或本轮预算',time_budget:'本轮时间预算'}[h.pause_reason]||h.pause_reason):''}。保存记录不等于进程存活，以任务状态为准。`;
    el('minuteDetailsTitle').textContent = `1 分钟标的列表 · 已补齐计划年份 ${inventory.plan_years_complete??'—'} 只`;
    const b=c.baostock||{};
    el('baoProgress').textContent=`BaoStock 全市场 5 分钟：${runStates[b.status]||b.status||'尚无记录'} · 名单 ${b.total_symbols??'—'} 只 · 本轮已检查 ${b.requests??0} 个标的年度 · 新增/修订 ${b.changed_rows??0} 行 · 错误 ${b.errors??0} · 当前 ${b.symbol||'—'} / ${b.year||'—'}。空返回与缺口单独留存，不代表历史完整。`;
    if(el('minuteDetails').open)drawList();
  }
  async function refresh(force=false) {
    if (loading) return; loading=true;
    try { const r=await fetch('/api/data/inventory'+(force?'?refresh=1':'')); if(!r.ok)throw Error(r.status); inventory=await r.json(); render(); }
    catch(e) { el('dataStamp').textContent='读取覆盖失败，保留上次显示：'+e.message; }
    finally { loading=false; }
  }
  async function tasks() {
    if(tasksLoading)return; tasksLoading=true;
    try { const r=await fetch('/api/data/tasks'); const d=await r.json();
      el('dataTasks').innerHTML = d.error?`任务状态无法确认：${escape(d.error)}`:(d.tasks||[]).map(t=>`<p><b>${escape(taskNames[t.name]||t.name)}</b> · ${escape(states[t.state]||t.state)} · 下次 ${escape(t.next_run)}<br><small>上次返回：${t.last_result===0?'正常结束（不等于数据完整）':t.last_result===267009?'仍在运行':t.last_result===2?'延后／需要检查':escape(t.last_result)}</small></p>`).join('');
      if(d.cache?.stale)el('dataTasks').innerHTML+='<p>任务状态缓存已过期，等待重新确认。</p>';
    } catch(e) {el('dataTasks').textContent='任务状态读取失败：'+e.message;} finally {tasksLoading=false;}
  }
  el('dataSync').onclick = async () => {
    const button=el('dataSync'); button.disabled=true; el('dataSyncMessage').textContent='正在提交同步请求…';
    try { const r=await fetch('/api/data/sync/'+el('dataSyncMode').value,{method:'POST',headers:{'X-Mining-Token':el('dataAcquisition').dataset.token}}); const d=await r.json(); if(!r.ok)throw Error(d.message||r.status);
      el('dataSyncMessage').textContent=(d.tasks||[]).map(t=>(taskNames[t.name]||t.name)+'：'+(states[t.state]||t.state)).join('；')+'。'+d.message; await tasks(); await refresh();
    } catch(e) {el('dataSyncMessage').textContent='同步请求未确认：'+e.message;} finally {button.disabled=false;}
  };
  el('dataRescan').onclick=()=>refresh(true);
  el('minuteSearch').oninput=el('minuteScope').onchange=()=>{page=0;drawList();};
  el('minutePrev').onclick=()=>{page--;drawList();}; el('minuteNext').onclick=()=>{page++;drawList();};
  el('minuteExport').onclick=()=>{
    const cell=x=>'"'+String(x??'').replace(/^[=+@-]/,"'$&").replaceAll('"','""')+'"';
    const rows=[['代码','名称','来源','最早已存','最新已存','富途最早可取','已存富途年份','待补年份','计划年份齐全（非逐日验证）'],...filtered().map(r=>[r.symbol,r.name,r.sources.join('/'),r.first,r.last,r.earliest_available,r.years.join('/'),r.missing_years.join('/'),r.plan_years_complete?'是':'否'])];
    const url=URL.createObjectURL(new Blob(['\ufeff'+rows.map(r=>r.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'})); const a=document.createElement('a');a.href=url;a.download='minute-data-coverage.csv';a.click();URL.revokeObjectURL(url);
  };
  const visible=()=>window.dashboardPage==='dataAcquisition'&&!document.hidden;
  el('minuteDetails').addEventListener('toggle',()=>{if(el('minuteDetails').open)drawList();});
  window.addEventListener('dashboard:page',()=>{if(visible()){refresh();tasks();}});
  window.addEventListener('dashboard:refresh',()=>{if(visible()){refresh(true);tasks();}});
  setInterval(()=>{if(visible())refresh();},15000);
  setInterval(()=>{if(visible())tasks();},30000);
})();
