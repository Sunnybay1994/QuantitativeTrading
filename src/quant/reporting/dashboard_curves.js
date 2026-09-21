/* Saved NAV comparison, no external libraries or network data sources. */
(()=>{
const by=id=>document.getElementById(id), colors=['#5ee1bd','#ffbe70','#7dafff','#df9fff','#ff8397','#c4db77','#72d7ef','#c6c9d2'];
let current,periods,periodQuery,request=0;
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function load(){
 try{
  const entries=await (await fetch('/api/curves')).json();
  if(!Array.isArray(entries))throw Error(entries.error||'曲线目录读取失败');
  by('curveStrategy').innerHTML=entries.filter(x=>x.kind!=='benchmark').map(x=>`<option value="${x.id}">${escape(x.label)}</option>`).join('');
  by('curveBenchmarks').innerHTML=entries.filter(x=>x.kind==='benchmark').map(x=>`<label style="display:inline-flex;align-items:center;gap:6px;margin:5px 14px 5px 0"><input style="min-width:0" type="checkbox" value="${x.id}" ${x.label.includes('H00905')?'checked':''}>${escape(x.label)} <small>${escape(x.currency+' · '+x.basis)}</small></label>`).join('');
  const preferred=entries.find(x=>x.kind==='strategy'&&x.label.includes(' · 1× · '));if(preferred)by('curveStrategy').value=preferred.id;
  await draw();
 }catch(e){by('curveInfo').textContent=e.message;by('periodDescription').textContent='期间报告不可用：'+e.message;}
}
async function draw(){
 const ticket=++request;
 const ids=[by('curveStrategy').value,...Array.from(by('curveBenchmarks').querySelectorAll('input:checked'),x=>x.value)].filter(Boolean);
 const range=by('curveRange').value;
 const q=new URLSearchParams();ids.forEach(id=>q.append('id',id));
 if(range==='custom'){q.set('start',by('curveStart').value);q.set('end',by('curveEnd').value);}
 else if(range!=='all')q.set('months',range);
 by('curveInfo').textContent='正在读取净值…';periods=null;by('periodRows').innerHTML='';by('periodDescription').textContent='正在计算期间表现…';by('periodNote').textContent='';by('periodDownload').disabled=true;
 try{
  const d=await(await fetch('/api/curve?'+q)).json();if(ticket!==request)return;if(d.error)throw Error(d.error);
  if(range!=='custom'){
   by('curveStart').value=d.start;by('curveEnd').value=d.end;
   q.delete('months');q.set('start',d.start);q.set('end',d.end);
  }
  current=d;render();
  const p=await(await fetch('/api/periods?'+q)).json();if(ticket!==request)return;if(p.error)throw Error(p.error);
  periods=p;periodQuery=q.toString();by('periodDescription').textContent=p.description+' · 原回测初始资金：'+(p.capital?Number(p.capital).toLocaleString()+' '+p.currency:'源记录未提供');
  by('periodNote').textContent=(p.sample?.lines||[]).join('；')+' '+p.note+' '+p.excluded.join('；');
  by('periodBenchmark').innerHTML=(p.rows[0]?.benchmark_results||[]).map(b=>`<option>${escape(b.benchmark)}</option>`).join('')||'<option>未选可比基准</option>';
  by('periodDownload').disabled=false;renderPeriods();
 }catch(e){if(ticket!==request)return;current=null;by('curvePlot').innerHTML='';by('curveLegend').innerHTML='';by('curveInfo').textContent=e.message;by('periodDescription').textContent='期间报告不可用：'+e.message;}
}
function render(){
 const d=current;if(!d)return;
 const W=1100,H=390,L=70,R=24,T=20,B=48;
 const dates=d.series.flatMap(s=>s.points.map(p=>Date.parse(p.date))), values=d.series.flatMap(s=>s.points.map(p=>p.value));
 const minDate=Math.min(...dates),maxDate=Math.max(...dates);let lo=Math.min(0,...values),hi=Math.max(0,...values);const pad=Math.max(.02,(hi-lo)*.06);lo-=pad;hi+=pad;
 const x=date=>L+(Date.parse(date)-minDate)/(maxDate-minDate)*(W-L-R),y=v=>T+(hi-v)/(hi-lo)*(H-T-B);
 let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="策略与基准累计收益曲线" style="width:100%;display:block">`;
 for(let i=0;i<=5;i++){const v=lo+(hi-lo)*i/5;svg+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="#28364a"/><text x="${L-10}" y="${y(v)+4}" text-anchor="end" fill="#96a9c0" font-size="12">${(v*100).toFixed(1)}%</text>`;}
 for(let i=0;i<=4;i++){const v=minDate+(maxDate-minDate)*i/4,xx=L+(W-L-R)*i/4;svg+=`<text x="${xx}" y="${H-15}" text-anchor="${i===0?'start':i===4?'end':'middle'}" fill="#96a9c0" font-size="12">${new Date(v).toISOString().slice(0,10)}</text>`;}
 d.series.forEach((s,i)=>{svg+=`<path d="${s.points.map((p,j)=>(j?'L':'M')+x(p.date).toFixed(2)+','+y(p.value).toFixed(2)).join(' ')}" fill="none" stroke="${colors[i]}" stroke-width="2"/>`;});
 svg+='</svg>';by('curvePlot').innerHTML=svg;
 by('curveInfo').textContent=`${d.start} — ${d.end} · ${d.note}`;
 by('curveLegend').innerHTML=d.series.map((s,i)=>`<div style="margin:7px 0;color:${colors[i]}">${escape(s.label)} · 区间收益 ${(s.points.at(-1).value*100).toFixed(2)}% <small>（${escape(s.currency+' / '+s.basis)}；源覆盖 ${s.coverage.join(' — ')}）</small></div>`).join('');
 by('curveSource').textContent=d.series.map(s=>s.label+'\n'+s.source.join('\n')).join('\n\n');
 const allDates=[...new Set(d.series.flatMap(s=>s.points.map(p=>p.date)))].sort();
 const slider=by('curveCursor');slider.max=allDates.length-1;slider.value=allDates.length-1;
 function inspect(){const date=allDates[Number(slider.value)];by('curveTooltip').textContent=date+' · '+d.series.map(s=>{const p=s.points.find(p=>p.date===date);return s.label+': '+(p?(p.value*100).toFixed(2)+'%':'当日无观测');}).join(' | ');}
 slider.oninput=inspect;inspect();
 by('curvePlot').onpointermove=e=>{const rect=by('curvePlot').getBoundingClientRect();const t=minDate+Math.max(0,Math.min(1,((e.clientX-rect.left)/rect.width*W-L)/(W-L-R)))*(maxDate-minDate);let best=0;allDates.forEach((v,i)=>{if(Math.abs(Date.parse(v)-t)<Math.abs(Date.parse(allDates[best])-t))best=i;});slider.value=best;inspect();};
}
const metric=(v,percent=true)=>v===null||v===undefined?'—':(v*(percent?100:1)).toFixed(percent?2:3)+(percent?'%':'');
function tableRows(rows){return rows.map(r=>{const b=r.benchmark_results.find(b=>b.benchmark===by('periodBenchmark').value);return `<tr><td>${escape(r.period)}</td><td title="${r.start} — ${r.end}">${r.sessions}</td><td>${metric(r.total_return)}</td><td>${metric(b?.total_return)}</td><td>${b?.excess_return==null?'—':(b.excess_return*100).toFixed(2)}</td><td>${metric(r.sharpe,false)}</td><td>${metric(r.sharpe_rf2,false)}</td><td>${metric(r.max_drawdown)}</td><td>${r.boundary_period?'边界期间':'区间内'}${r.sessions<20?' / 短样本':''}${b&&b.status!=='complete'?' / 基准缺口':''}</td></tr>`;}).join('');}
function renderPeriods(){if(!periods)return;by('periodRows').innerHTML=tableRows(periods.rows.filter(r=>r.frequency===by('periodFrequency').value))||'<tr><td colspan="9">无持仓期指标</td></tr>';}
by('periodFrequency').onchange=renderPeriods;by('periodBenchmark').onchange=renderPeriods;
by('periodDownload').onclick=()=>{if(!periods)return;const q=new URLSearchParams(periodQuery);q.set('benchmark',by('periodBenchmark').value);const a=document.createElement('a');a.href='/api/period-report?'+q;a.download='strategy-period-report.html';document.body.appendChild(a);a.click();a.remove();};
by('curveDraw').onclick=draw;by('curveStrategy').onchange=draw;by('curveBenchmarks').onchange=draw;
by('curveRange').onchange=draw;
by('curveStart').onchange=by('curveEnd').onchange=()=>{by('curveRange').value='custom';};
by('curveReset').onclick=()=>{by('curveRange').value='all';draw();};
window.addEventListener('dashboard:refresh',()=>{if(window.dashboardPage==='curves')draw();});
load();
})();
