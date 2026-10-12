(() => {
  'use strict';
  const root = document.querySelector('#fee-settings');
  const $ = selector => root.querySelector(selector);
  const state = JSON.parse(root.dataset.state);
  let simulationSequence = 0, simulationTimer;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const copy = value => JSON.parse(JSON.stringify(value));
  const money = value => new Intl.NumberFormat('ja-JP').format(value) + '円';
  const calc = window.FeePreviewCalculator;
  const categories = ['standard', 'short'];
  const labels = {standard:'保育標準時間', short:'保育短時間'};
  const shortLabel = {standard:'標準時間', short:'短時間'};
  const sideLabel = {morning:'前延長', evening:'あと延長'};
  let sequence = 0, draft = {}, saved = {}, baseline = {}, undo = {}, errorsVisible = {}, pendingSave = null, pendingDiscard = null, toastTimer;
  function band(start = '', end = '', unit = '10', price = '') {return {id:'band'+(++sequence),start,end,mode:'unit',unit,price};}
  function emptyPlan(category) {return {name:shortLabel[category]+'の延長保育料',from:'',to:'',active:true,normalStart:'',normalEnd:'',morningEnabled:null,eveningEnabled:null,morningGrace:'0',eveningGrace:'0',morningBands:[],eveningBands:[],cap:''};}
  function loadRules() {
    categories.forEach(category=>{
      const rules=state.rules[category];
      const active=rules.find(p=>p.active&&p.from<=state.today&&(!p.to||p.to>=state.today));
      const p=active||rules[0]||emptyPlan(category);
      draft[category]=copy(p); baseline[category]=copy(p); saved[category]=p.id?copy(p):null; undo[category]={};
    });
    $('#plan-cards').innerHTML=categories.map(renderPlan).join(''); refresh();
  }
  async function api(path,payload) {
    const response=await fetch('/extended-care-fees/settings/bands/'+path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]')?.content||''},body:JSON.stringify(payload)});
    if(response.redirected)throw new Error('ログイン状態を確認してください。入力はこの画面に残っています。');
    let data;try{data=await response.json();}catch{throw new Error('応答を確認できませんでした。入力を控えて保存状況を確認してください。');}
    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'保存できませんでした。入力を確認してください。');
    return data;
  }
  function historyPicker(category,p) {
    return '<div class="history-picker"><label>編集する適用期間<select data-history="'+category+'" aria-label="'+shortLabel[category]+' 編集する適用期間">'+state.rules[category].map(item=>'<option value="'+item.id+'" '+(item.id===p.id?'selected':'')+'>'+esc(item.from+'〜'+(item.to||'終了日なし')+' ／ '+item.name+(item.active?'':'（無効）'))+'</option>').join('')+'<option value="new" '+(!p.id?'selected':'')+'>＋ 新しい期間のルール</option></select></label>'+(p.existingCalculation?'<p class="notice">現在は時間帯を指定しない従来の計算方法です。使用する延長の開始・終了を入力して保存すると、時間帯別の計算へ切り替わります。保存までは現在の計算を維持します。</p>':'')+'</div>';
  }
  const dirty = category => JSON.stringify(draft[category]) !== JSON.stringify(baseline[category]);
  function field(category, key, label, value, type='text', attributes='') {
    return '<label>'+label+'<input type="'+type+'" data-field="'+key+'" value="'+esc(value)+'" aria-label="'+shortLabel[category]+' '+esc(label)+'" '+attributes+'></label>';
  }
  function renderBand(category, side, row, index) {
    const name = shortLabel[category]+' '+sideLabel[side]+(index+1);
    const input = (key,label,type,extra='') => '<label'+(type==='time'?' class="time-label"':'')+'>'+label+'<input type="'+type+'" data-field="'+key+'" data-side="'+side+'" data-band="'+row.id+'" value="'+esc(row[key])+'" aria-label="'+name+' '+label+'" '+extra+'></label>';
    return '<div class="band"><div class="band-title"><strong>'+sideLabel[side]+' '+(index+1)+'</strong><button type="button" class="remove-band" data-remove="'+row.id+'" data-side="'+side+'" aria-label="'+name+'を削除">削除</button></div><div class="band-fields">'+input('start','開始','time')+input('end','終了','time')+'</div><div class="band-rate"><label>料金方式<select data-field="mode" data-side="'+side+'" data-band="'+row.id+'" aria-label="'+name+' 料金方式"><option value="unit" '+(row.mode==='unit'?'selected':'')+'>時間ごとに課金</option><option value="flat" '+(row.mode==='flat'?'selected':'')+'>時間帯ごと定額</option></select></label>'+input('unit','何分ごと','number','min="1" max="120" '+(row.mode==='flat'?'disabled':''))+input('price',row.mode==='flat'?'1回の料金（円）':'1単位の料金（円）','number','min="0" placeholder="金額"')+'</div><p class="band-note">'+(row.mode==='flat'?'この時間帯を利用したら1回分。':'端数はこの時間帯の中で切り上げます。')+'</p></div>';
  }
  function renderExtension(category, side) {
    const plan=draft[category], enabled=plan[side+'Enabled'];
    let html='<section class="extension"><div class="extension-head"><div><h3>'+sideLabel[side]+'</h3><small>通常保育'+(side==='morning'?'の前':'のあと')+'</small></div><div class="segmented" role="group" aria-label="'+shortLabel[category]+' '+sideLabel[side]+'の使用">';
    for(const [value,label] of [[true,'使用する'],[false,'使用しない']]) html+='<label><input type="radio" name="'+category+'-'+side+'" data-field="'+side+'Enabled" value="'+value+'" '+(enabled===value?'checked':'')+' aria-label="'+shortLabel[category]+' '+sideLabel[side]+' '+label+'"><span>'+label+'</span></label>';
    html+='</div></div>';
    if(enabled===true) {
      html+='<div class="bands">'+plan[side+'Bands'].map((row,i)=>renderBand(category,side,row,i)).join('')+'</div><button type="button" class="add-band" data-add="'+side+'">＋ '+sideLabel[side]+'の時間帯を追加</button>';
      if(undo[category][side]) html+='<div class="undo-row"><span>時間帯を削除しました</span><button type="button" data-undo="'+side+'">削除を戻す</button></div>';
      html+='<div class="grace"><label>通常保育との境界の猶予<input type="number" min="0" max="120" data-field="'+side+'Grace" value="'+esc(plan[side+'Grace'])+'" aria-label="'+shortLabel[category]+' '+sideLabel[side]+'の猶予">分</label><span>途中の区切りでは再適用しません。</span></div>';
    } else html+='<p class="inactive-note">'+(enabled===false?'<strong>'+sideLabel[side]+'は使用しません。</strong><br>使用するに戻すと、入力した時間帯を復元します。':'「使用する」か「使用しない」を選んでください。')+'</p>';
    return html+'</section>';
  }
  function renderPlan(category) {
    const p=draft[category];
    return '<article class="card plan-card '+category+'" id="plan-'+category+'"><header class="plan-head"><div><h2>'+labels[category]+'</h2><p>区分はこの枠に固定されています</p></div><span class="tag" data-plan-status="'+category+'"></span></header>'+historyPicker(category,p)+'<form id="plan-form-'+category+'" data-category="'+category+'" novalidate><fieldset '+(!state.canEdit?'disabled':'')+'><div class="plan-body"><div class="plan-errors" data-errors="'+category+'" tabindex="-1" role="alert" hidden></div><fieldset class="normal-box"><legend>1. 通常保育時間 <span>この時間内は延長料金がかかりません</span></legend><div class="two-times">'+field(category,'normalStart','開始',p.normalStart,'time')+'<span>〜</span>'+field(category,'normalEnd','終了',p.normalEnd,'time')+'</div></fieldset>'+renderExtension(category,'morning')+renderExtension(category,'evening')+'<section class="plan-meta"><h3>適用期間と保存する内容</h3>'+field(category,'name','ルール名',p.name,'text','maxlength="100"')+'<div class="dates">'+field(category,'from','適用開始日',p.from,'date')+field(category,'to','適用終了日（任意）',p.to,'date')+'</div><div class="cap-active">'+field(category,'cap','日別上限額（円・任意）',p.cap,'number','min="0" placeholder="上限なし"')+'<label class="check"><input type="checkbox" data-field="active" '+(p.active?'checked':'')+'>このルールを有効にする</label></div><p class="small muted">上限は前延長・あと延長の合計に適用します。</p></section></div><footer class="card-footer"><p data-save-state="'+category+'"></p><button type="button" data-discard="'+category+'">変更を戻す</button><button type="submit" class="primary">'+shortLabel[category]+'の保存内容を確認</button></footer></fieldset></form></article>';
  }
  function rerender(category, focus) {
    $('#plan-'+category).outerHTML = renderPlan(category);
    refresh();
    if(focus) $('#plan-'+category+' '+focus)?.focus();
  }
  function showErrors(category) {
    const container=$('[data-errors="'+category+'"]');
    const errors=errorsVisible[category]?calc.validate(draft[category]):[];
    container.hidden=!errors.length;
    container.innerHTML='<strong>入力を確認してください</strong><ul>'+errors.map(item=>'<li>'+esc(item.message)+'</li>').join('')+'</ul>';
    $('#plan-'+category).querySelectorAll('[aria-invalid]').forEach(input=>input.removeAttribute('aria-invalid'));
    errors.forEach(item=>{
      const selector='[data-field="'+item.field+'"]'+(item.id?'[data-band="'+item.id+'"]':'');
      $('#plan-'+category).querySelectorAll(selector).forEach(input=>input.setAttribute('aria-invalid','true'));
    });
    return errors;
  }
  function refresh() {
    categories.forEach(category=>{
      const invalid=showErrors(category).length>0;
      const status=$('[data-plan-status="'+category+'"]');
      status.className='tag '+(invalid?'error':dirty(category)?'dirty':saved[category]?'saved':'neutral');
      status.textContent=invalid?'入力を要確認':dirty(category)?'未保存の変更':saved[category]?(draft[category].active?'保存済み':'保存済み・無効'):'未設定';
      $('[data-save-state="'+category+'"]').textContent=dirty(category)?'まだ保存されていません':saved[category]?'保存済みの内容':'保存すると設定済みになります';
    });
    const readiness=categories.map(category=>shortLabel[category]+'：'+(state.rules[category].some(p=>p.active&&p.from<=state.today&&(!p.to||p.to>=state.today))?'設定済み':'今日に有効な設定なし')).join(' ／ ');
    $('#mode-status').textContent=readiness+'。切替前は下の従来ルールで計算します。';
    runSimulation();
  }
  async function runSimulation() {
    const category=$('#sim-category').value, p=draft[category];
    clearTimeout(simulationTimer); const sequence=++simulationSequence;
    $('#sim-result').textContent='試算中…';
    simulationTimer=setTimeout(async()=>{
    let result;try{result=await api('preview',{plan:p,date:$('#sim-date').value,arrival:$('#sim-arrival').value,departure:$('#sim-departure').value});}catch(error){result={errors:[error.message]};}
    if(sequence!==simulationSequence)return;

    if(result.errors.length) {$('#sim-result').innerHTML='<div class="sim-warning"><strong>設定を確認すると試算できます</strong><ul>'+result.errors.map(error=>'<li>'+esc(error)+'</li>').join('')+'</ul></div>';return;}
    let html=result.warnings.length?'<div class="sim-warning"><strong>合計は要確認です</strong><ul>'+result.warnings.map(warning=>'<li>'+esc(warning)+'</li>').join('')+'</ul></div>':'';
    html+='<div class="result-layout"><div><table class="result-table"><thead><tr><th>使用した時間帯</th><th>計算の内訳</th><th>料金</th></tr></thead><tbody>';
    html+=result.lines.length?result.lines.map(line=>'<tr><td>'+esc(line.label)+' '+esc(line.range)+'<small>利用 '+esc(line.usedRange)+'（'+line.used+'分）</small></td><td>'+esc(line.method)+'<small>'+line.units+' × '+money(line.price)+'</small></td><td>'+money(line.amount)+'</td></tr>').join(''):'<tr><td colspan="3">'+(result.warnings.length?'設定済み時間帯での課金はありません。':'通常保育時間内、または猶予時間内のため0円です。')+'</td></tr>';
    html+='</tbody></table></div><div class="result-total '+(result.total===null?'warning':'')+'"><span>'+labels[category]+'の試算</span><strong>'+(result.total===null?'合計は要確認':new Intl.NumberFormat('ja-JP').format(result.total)+'<small>円</small>')+'</strong><p>'+(result.total===null?'設定内の小計 '+money(result.subtotal):result.capped?'小計 '+money(result.subtotal)+' → 日別上限 '+money(result.cap)+' を適用':'前延長・あと延長の合計')+'</p><p>保存前の入力内容で計算</p></div></div>';
    $('#sim-result').innerHTML=html;
    },250);
  }
  function toast(message) {clearTimeout(toastTimer);$('#toast').textContent=message;$('#toast').hidden=false;toastTimer=setTimeout(()=>{$('#toast').hidden=true;},5000);}
  function openConfirmation(title, html, action, button='この設定を保存') {
    pendingSave=action;$('#confirm-title').textContent=title;$('#confirm-body').innerHTML=html;$('#confirm-error').hidden=true;$('#confirm-save').textContent=button;$('#confirm-dialog').showModal();
  }
  function formatBands(plan, side) {
    if(plan[side+'Enabled']===false)return '使用しない';
    if(plan[side+'Enabled']!==true)return '未設定';
    return plan[side+'Bands'].map(row=>row.start+'〜'+row.end+' ／ '+(row.mode==='flat'?'時間帯ごと':row.unit+'分ごと')+money(Number(row.price))).join('、')+' ／ 境界の猶予'+plan[side+'Grace']+'分';
  }
  function planSummary(plan) {
    if(!plan)return '<p class="muted">この区分はまだ保存されていません。</p>';
    const values=[['通常保育',plan.normalStart+'〜'+plan.normalEnd],['前延長',formatBands(plan,'morning')],['あと延長',formatBands(plan,'evening')],['適用期間',plan.from+'〜'+(plan.to||'終了日なし')],['日別上限',plan.cap===''?'上限なし':money(Number(plan.cap))],['状態',plan.active?'有効':'無効'],['ルール名',plan.name]];
    return '<dl class="diff">'+values.map(([label,value])=>'<dt>'+label+'</dt><dd>'+esc(value)+'</dd>').join('')+'</dl>';
  }
  function savePlan(category) {
    errorsVisible[category]=true;
    if(showErrors(category).length) {refresh();$('[data-errors="'+category+'"]').focus();return;}
    if(saved[category]&&!dirty(category)){toast('保存済みの内容から変更はありません。');return;}
    const candidate=copy(draft[category]);
    openConfirmation(labels[category]+'の保存内容', '<p class="notice">'+labels[category]+'として保存します。もう一方の区分は変更しません。</p>'+planSummary(candidate)+'<details class="quiet-details"><summary>保存前の内容を見る</summary>'+planSummary(saved[category])+'</details><p>設定の保存だけでは過去の料金は変わりません。保存後に対象月を選んで確認します。</p>',async()=>{
      const result=await api(category,candidate);
      const index=state.rules[category].findIndex(p=>p.id===result.id);if(index>=0)state.rules[category][index]=result;else state.rules[category].unshift(result);
      draft[category]=copy(result);saved[category]=copy(result);baseline[category]=copy(result);errorsVisible[category]=false;undo[category]={};rerender(category);toast(labels[category]+'の設定を保存しました。');
    });
  }
  function requestDiscard(text, action) {pendingDiscard=action;$('#discard-text').textContent=text;$('#discard-dialog').showModal();}
  root.querySelectorAll('button:not([type])').forEach(button=>{if(!button.closest('form'))button.type='button';});
  $('#plan-cards').addEventListener('submit',event=>{event.preventDefault();savePlan(event.target.dataset.category);});
  $('#plan-cards').addEventListener('input',event=>{
    const el=event.target, form=el.closest('[data-category]');
    if(!form||!el.dataset.field)return;
    const category=form.dataset.category, key=el.dataset.field, p=draft[category];
    if(el.dataset.band){const row=p[el.dataset.side+'Bands'].find(row=>row.id===el.dataset.band);row[key]=el.value;}
    else p[key]=el.type==='checkbox'?el.checked:el.type==='radio'?el.value==='true':el.value;
    if(el.type==='radio') {
      const side=key.startsWith('morning')?'morning':'evening';
      if(p[key]&&!p[side+'Bands'].length)p[side+'Bands'].push(band(side==='evening'?p.normalEnd:'',side==='morning'?p.normalStart:''));
      rerender(category,'[data-field="'+key+'"][value="'+el.value+'"]');
    } else if(key==='mode')rerender(category,'[data-band="'+el.dataset.band+'"][data-field="mode"]');
    else refresh();
  });
  $('#plan-cards').addEventListener('click',event=>{
    const button=event.target.closest('button'), form=button?.closest('[data-category]');
    if(!button||!form)return;
    const category=form.dataset.category,p=draft[category];
    if(button.dataset.add){const side=button.dataset.add,rows=p[side+'Bands'];const next=side==='morning'?band('',rows[0]?.start||p.normalStart):band(rows.at(-1)?.end||p.normalEnd,'');if(side==='morning')rows.unshift(next);else rows.push(next);rerender(category,'[data-band="'+next.id+'"][data-field="'+(side==='morning'?'start':'end')+'"]');}
    if(button.dataset.remove){const side=button.dataset.side,rows=p[side+'Bands'],index=rows.findIndex(row=>row.id===button.dataset.remove);undo[category][side]={band:rows[index],index};rows.splice(index,1);rerender(category,'[data-undo="'+side+'"]');}
    if(button.dataset.undo){const side=button.dataset.undo,item=undo[category][side];p[side+'Bands'].splice(item.index,0,item.band);delete undo[category][side];rerender(category);}
    if(button.dataset.discard){if(!dirty(category))return toast('未保存の変更はありません。');requestDiscard(labels[category]+'の未保存の入力を戻します。',()=>{draft[category]=copy(baseline[category]);errorsVisible[category]=false;undo[category]={};rerender(category);toast('未保存の変更を戻しました。');});}
  });
  ['sim-category','sim-date','sim-arrival','sim-departure'].forEach(id=>$('#'+id).addEventListener('input',runSimulation));
  document.querySelectorAll('[data-leave]').forEach(button=>button.addEventListener('click',()=>{$('#sim-departure').value=button.dataset.leave;runSimulation();}));
  document.querySelectorAll('[data-close]').forEach(button=>button.addEventListener('click',()=>$('#'+button.dataset.close).close()));
  $('#confirm-save').addEventListener('click',async()=>{
    const button=$('#confirm-save');button.disabled=true;
    try {await pendingSave?.();$('#confirm-dialog').close();pendingSave=null;}
    catch(error){$('#confirm-error').textContent=error.message;$('#confirm-error').hidden=false;}
    finally {button.disabled=false;}
  });
  $('#discard-yes').addEventListener('click',()=>{pendingDiscard?.();$('#discard-dialog').close();pendingDiscard=null;});
  $('#plan-cards').addEventListener('change',event=>{
    const category=event.target.dataset.history;if(!category)return;
    const value=event.target.value;
    const change=()=>{const p=value==='new'?emptyPlan(category):state.rules[category].find(p=>String(p.id)===value);draft[category]=copy(p);baseline[category]=copy(p);saved[category]=p.id?copy(p):null;errorsVisible[category]=false;undo[category]={};rerender(category);};
    if(dirty(category)){event.target.value=draft[category].id||'new';requestDiscard('未保存の変更を戻して、別の適用期間を開きます。',change);}else change();
  });
  $('#preview-recalc').addEventListener('click',()=>{location.href='/extended-care-fees/?month='+encodeURIComponent($('#recalc-month').value);});
  function bindOtherForms(container){container.querySelectorAll('#mode-form,#billing-form,.legacy-form').forEach(form=>form.addEventListener('submit',event=>{
    event.preventDefault();const data=new URLSearchParams(new FormData(form));
    openConfirmation('設定内容を保存','<p>この設定を保存します。料金ルールの保存だけでは過去の料金は変わりません。</p>',async()=>{
      const response=await fetch(form.action,{method:'POST',credentials:'same-origin',headers:{'X-CSRF-Token':document.querySelector('meta[name="csrf-token"]')?.content||''},body:data});
      if(!response.ok){const type=response.headers.get('content-type')||'';if(type.includes('json')){const body=await response.json();throw new Error(typeof body.detail==='string'?body.detail:'入力を確認してください。');}const doc=new DOMParser().parseFromString(await response.text(),'text/html');const errors=[...doc.querySelectorAll('.bg-red-50')].map(e=>e.textContent.trim()).join(' / ');throw new Error(errors||'入力を確認してください。');}
      if(response.url.includes('/staff/login'))throw new Error('ログイン状態を確認してください。入力は残っています。');
      const doc=new DOMParser().parseFromString(await response.text(),'text/html');
      const latest=doc.querySelector('#fee-settings');
      if(!latest)throw new Error('保存結果の画面を確認できませんでした。入力を控えて保存状況を確認してください。');
      if(form.id==='billing-form')form.closest('details').querySelector('.tag').textContent=data.has('is_enabled')?'有効':'無効';
      if(form.classList.contains('legacy-form')){
        const currentSection=form.closest('.supplemental');
        const updatedSection=[...latest.querySelectorAll('.supplemental')].find(e=>e.querySelector('.legacy-form'));
        if(updatedSection){currentSection.replaceWith(updatedSection);bindOtherForms(updatedSection);updatedSection.open=true;}
      }
      toast('設定を保存しました。');
    });
  }));}
  bindOtherForms(root);
  window.addEventListener('beforeunload',event=>{if(categories.some(dirty)){event.preventDefault();event.returnValue='';}});
  loadRules();
})();
