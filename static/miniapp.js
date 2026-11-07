(() => {
  const tg = window.Telegram?.WebApp;
  const $ = (id) => document.getElementById(id);
  const state = {token:"", games:[], game:null, product:null, idChecked:false, manual:false};
  const money = n => new Intl.NumberFormat('uz-UZ',{maximumFractionDigits:0}).format(Number(n||0)) + " so'm";
  const notice = (msg,bad=false) => { $('notice').textContent=msg; $('notice').classList.toggle('bad',bad); $('notice').classList.remove('hidden'); };
  const api = async (path, body=null) => {
    const opts = {method:body?'POST':'GET',headers:{'Content-Type':'application/json'}};
    if(state.token) opts.headers.Authorization='Bearer '+state.token;
    if(body) opts.body=JSON.stringify(body);
    const r=await fetch(path,opts); const data=await r.json().catch(()=>({ok:false,error:'Server javobi noto‘g‘ri.'}));
    if(!r.ok || data.ok===false) throw new Error(data.error||'Xatolik yuz berdi.');
    return data;
  };
  function resetCheck(){state.idChecked=false;state.manual=false;$('orderBtn').disabled=true;$('checkResult').className='hint';$('checkResult').textContent='ID tekshirilgandan keyin buyurtma berishingiz mumkin.';}
  async function boot(){
    if(!tg){notice('Mini App faqat Telegram ichida ochiladi.',true);return;}
    tg.ready();tg.expand();tg.setHeaderColor?.('#0b1220');tg.setBackgroundColor?.('#0b1220');
    try{
      const auth=await api('/api/mini/auth',{init_data:tg.initData||''});state.token=auth.token;
      $('balance').textContent=money(auth.balance);
      const cat=await api('/api/catalog');state.games=cat.games||[];
      $('game').innerHTML='<option value="">O‘yin tanlang</option>'+state.games.map(g=>`<option value="${g.game_id}">${esc(g.name)}</option>`).join('');
    }catch(e){notice(e.message,true);}
  }
  function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  $('game').addEventListener('change',()=>{
    state.game=state.games.find(g=>String(g.game_id)===$('game').value)||null;state.product=null;resetCheck();
    const ps=state.game?.packages||[];$('package').disabled=!ps.length;
    $('package').innerHTML=ps.length?'<option value="">Paket tanlang</option>'+ps.map(p=>`<option value="${p.paket_id}">${esc(p.name)} — ${money(p.price)}</option>`).join(''):'<option value="">Paket mavjud emas</option>';
    $('serverWrap').classList.toggle('hidden',!state.game?.requires_server);$('price').textContent=money(0);
  });
  $('package').addEventListener('change',()=>{state.product=state.game?.packages.find(p=>String(p.paket_id)===$('package').value)||null;$('price').textContent=money(state.product?.price);resetCheck();});
  $('playerId').addEventListener('input',resetCheck);$('serverId').addEventListener('input',resetCheck);
  $('checkBtn').addEventListener('click',async()=>{
    if(!state.game||!state.product||!$('playerId').value.trim()){notice('O‘yin, paket va ID ni kiriting.',true);return;}
    $('checkBtn').disabled=true;$('checkResult').className='hint';$('checkResult').textContent='ID tekshirilmoqda…';
    try{
      const d=await api('/api/check-id',{game_id:state.game.game_id,player_id:$('playerId').value.trim(),server_id:$('serverId').value.trim()});
      if(d.manual){state.manual=true;state.idChecked=true;$('checkResult').className='hint ok';$('checkResult').textContent='Grand Mobile ID qabul qilindi. Buyurtma manual tekshiriladi.';}
      else if(d.valid===true){state.idChecked=true;$('checkResult').className='hint ok';$('checkResult').textContent='ID qabul qilindi.'+(d.player_name?' O‘yinchi: '+d.player_name:'');}
      else throw new Error(d.error||'ID tasdiqlanmadi.');
      $('orderBtn').disabled=false;
    }catch(e){state.idChecked=false;$('checkResult').className='hint bad';$('checkResult').textContent=e.message;}
    finally{$('checkBtn').disabled=false;}
  });
  $('orderBtn').addEventListener('click',async()=>{
    if(!state.idChecked||!state.game||!state.product)return;
    const confirmText=`${state.game.name}\n${state.product.name}\nID: ${$('playerId').value.trim()}\nNarx: ${money(state.product.price)}\nBuyurtmani tasdiqlaysizmi?`;
    const proceed=()=>placeOrder();
    if(tg?.showConfirm) tg.showConfirm(confirmText,ok=>{if(ok)proceed();}); else if(window.confirm(confirmText)) proceed();
  });
  async function placeOrder(){
    $('orderBtn').disabled=true;
    try{
      const d=await api('/api/order',{game_id:state.game.game_id,paket_id:state.product.paket_id,player_id:$('playerId').value.trim(),server_id:$('serverId').value.trim()});
      notice('✅ '+(d.message||'Buyurtma qabul qilindi.'));
      const me=await api('/api/me');$('balance').textContent=money(me.balance);resetCheck();
      tg?.HapticFeedback?.notificationOccurred('success');
    }catch(e){notice(e.message,true);$('orderBtn').disabled=false;tg?.HapticFeedback?.notificationOccurred('error');}
  }
  boot();
})();
