(() => {
  const el=id=>document.getElementById(id);
  const names={email:'邮件 SMTP',wecom:'企业微信群机器人',feishu:'飞书群机器人',wxauto:'个人微信'};
  const fields={email:[['smtp_host','SMTP服务器'],['smtp_port','端口（STARTTLS）'],['from_addr','发件人'],['to_addrs','收件人（逗号分隔）'],['username','登录名'],['password','SMTP授权码']],wecom:[['webhook','机器人HTTPS地址']],feishu:[['webhook','机器人HTTPS地址']],wxauto:[['group','精确群名（需微信登录、桌面解锁）']]};
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let built=false, loading=false, busy=false;
  async function post(action,body={}) {
    const r=await fetch('/api/notifications/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Mining-Token':el('notifications').dataset.token},body:JSON.stringify(body)});
    const d=await r.json();if(!r.ok)throw Error(d.message||'操作失败');return d;
  }
  async function act(action,body={}) {
    if(busy)return;busy=true;el('notifyMessage').textContent='处理中…';
    el('notifications').querySelectorAll('button').forEach(b=>b.disabled=true);
    try {const d=await post(action,body);el('notifyMessage').textContent=d.message;}
    catch(e){el('notifyMessage').textContent='未完成：'+e.message;}
    finally {busy=false;el('notifications').querySelectorAll('button').forEach(b=>b.disabled=false);await refresh();}
  }
  async function refresh() {
    if(window.dashboardPage!=='notifications'||document.hidden||loading)return;loading=true;
    try {
      const r=await fetch('/api/notifications',{cache:'no-store'}),d=await r.json();if(d.error)throw Error(d.error);
      if(!built){
        el('notifyChannels').innerHTML=d.channels.map(row=>`<details class="panel"><summary>${names[row.channel]} · 单向通知</summary><form data-channel="${row.channel}">${fields[row.channel].map(([key,label])=>`<label style="display:inline-block;margin:8px">${label}<br><input name="${key}" type="${['password','webhook'].includes(key)?'password':'text'}" value="${esc(Array.isArray(row.values[key])?row.values[key].join(','):row.values[key]||'')}" autocomplete="off" placeholder="${row.secret_saved&&['password','webhook'].includes(key)?'已保存，留空保留':'请输入'}"></label>`).join('')}<p><label><input type="checkbox" name="enabled" ${row.enabled?'checked':''}> 启用自动通知</label> <button type="submit">保存配置 / 启停通知</button> <button type="button" data-test="${row.channel}">发送测试通知</button></p><small>此通道不支持后台回复监听。发送测试会实际发消息；密码留空保留。</small><p data-summary></p></form></details>`).join('');
        el('notifyChannels').querySelectorAll('form').forEach(form=>form.onsubmit=e=>{e.preventDefault();const values=Object.fromEntries(new FormData(form));delete values.enabled;act('save',{channel:form.dataset.channel,values,enabled:form.elements.enabled.checked});form.querySelectorAll('input[type=password]').forEach(x=>x.value='');});
        el('notifyChannels').querySelectorAll('[data-test]').forEach(b=>b.onclick=()=>act('test',{channel:b.dataset.test}));built=true;
      }
      for(const row of d.channels)el('notifyChannels').querySelector(`[data-channel="${row.channel}"] [data-summary]`).textContent=`自动通知：${row.enabled?'启用':'停用'} · 密钥：${row.secret_saved?'已保存':'未保存或不适用'}`;
      el('notifyAppStatus').textContent=`应用凭据：${d.app_configured?'已保存':'未配置'} · ${d.binding?'已绑定 '+d.binding.sender_id+' / '+d.binding.chat_id:'尚未绑定'}`;
      const b=d.binding_progress||{},labels={idle:'未进行绑定',connecting:'连接中，请等待口令就绪',waiting:'已连接，请发给机器人（群聊需@机器人）：',found:'已收到，请确认这是你的会话：',failed:'绑定失败'};
      el('notifyBinding').textContent=(labels[b.state]||b.state||'')+(b.state==='waiting'?' '+b.code:'')+(b.candidate?' '+b.candidate.sender_id+' / '+b.candidate.chat_id:'')+(b.message?' '+b.message:'');
      el('notifyConfirm').hidden=b.state!=='found';
      const x=d.listener||{};el('notifyListener').textContent=`进程：${x.process_alive?'运行中':'未运行'} · 连接：${x.connected?'已连接':'未连接或等待重连'} · 最近收信：${x.last_received||'暂无'}${x.error?' · 错误：'+x.error:''}`;
      if(!busy){el('notifyTest').disabled=!x.connected;el('notifyStart').disabled=x.process_alive;el('notifyStop').disabled=!x.process_alive;}
      el('notifySent').textContent=d.last_send?`${d.last_send.at||''} · ${d.last_send.provider_accepted?'平台已接受':(d.last_send.results||[]).map(x=>x.channel+': '+(x.ok?'成功':'失败')+' '+x.detail).join('；')}\n${d.last_send.expected_reply?'可复制回复：'+d.last_send.expected_reply:''}`:'尚未测试';
      el('notifyReceived').innerHTML=d.received.slice().reverse().map(m=>`<div class="panel"><small>${esc(m.received_at)} · 回执：${esc(({accepted:'平台已接受',queued:'待发送',sending:'发送结果待核',uncertain:'结果不明，未自动重发',legacy:'历史记录'})[m.ack_status]||'未知')} · ${m.parsed?'已解析固定格式回报（未入账）':'普通消息'}</small><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(m.text)}</pre>${m.parsed?'<pre>'+esc(JSON.stringify(m.parsed,null,2))+'</pre>':''}</div>`).join('')||'尚未收到消息';
    }catch(e){el('notifyMessage').textContent='读取失败：'+e.message;}finally{loading=false;}
  }
  el('notifyCredentials').onsubmit=e=>{e.preventDefault();const values=Object.fromEntries(new FormData(e.target));act('credentials',values);e.target.reset();};
  el('notifyBind').onclick=()=>act('bind');el('notifyConfirm').onclick=()=>act('confirm-binding');
  el('notifyStart').onclick=()=>act('start');el('notifyStop').onclick=()=>act('stop');el('notifyTest').onclick=()=>act('test',{channel:'feishu_app'});
  window.addEventListener('dashboard:page',refresh);window.addEventListener('dashboard:refresh',refresh);setInterval(refresh,3000);refresh();
})();
