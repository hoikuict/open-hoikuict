(() => {
  'use strict';
  const fixture = window.ParentGuardianFixture;
  const view = document.querySelector('#mock-view');
  const kind = document.querySelector('#preview-kind');
  const state = document.querySelector('#preview-state');
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let submitted = null;
  function message(text) {
    let error = view.querySelector('[role=alert]');
    if (!error) { error=document.createElement('p'); error.className='error'; error.setAttribute('role','alert'); view.querySelector('h1').after(error); }
    error.textContent=text; error.scrollIntoView({block:'center'});
  }
  function renderInput() {
    submitted=null;
    document.querySelector('#preview-scope').textContent = kind.value==='invite'
      ? '提案：選んだ保護者本人の登録済み9項目を表示。内容を確認し、不足・変更だけ入力して提出します。園の承認後に反映します。'
      : kind.value==='new' ? '比較用：新入園は従来の28項目。今回の引継ぎ対象ではありません。'
      : kind.value==='current' ? '比較用：実機の現行版。保護者を選んでも9項目が空欄です。'
      : '新しい保護者は空欄から9項目を入力します。別の保護者の情報は引き継ぎません。';
    if (state.value==='expired') {
      view.innerHTML='<h1>入力時間を過ぎました</h1><p class="error" role="alert">招待リンクから手続きをやり直してください。リンクも期限切れの場合は園へ再招待を依頼してください。</p>';return;
    }
    view.innerHTML=fixture.views[kind.value];
    const form=view.querySelector('form');
    const fields=[...form.querySelectorAll('input[name],textarea[name]')];
    const partial=['g1_last_name','g1_first_name','g1_last_name_kana','g1_first_name_kana','g1_relationship'];
    for (const field of fields) {
      const initial = kind.value==='invite' && state.value==='initial';
      const filled = ['filled','error'].includes(state.value) || (state.value==='partial' && partial.includes(field.name));
      field.value=initial ? fixture.registered[field.name]||'' : filled ? fixture.sample[field.name]||'' : '';
      if (kind.value==='new' && ['last_name','first_name'].includes(field.name)) field.value=fixture.sample[field.name];
      if (['filled','error'].includes(state.value) && field.name==='g1_phone') field.value='090-0000-1234';
      field.addEventListener('input',()=>field.classList.remove('invalid'));
    }
    if (state.value==='error') {
      const phone=form.querySelector('[name=g1_phone]');phone.value='';phone.classList.add('invalid');
      message('電話番号を入力してください。入力したほかの項目は保持しています。');
    }
    const cancel=form.querySelector('#cancel-guardian-registration');
    if (cancel) {
      cancel.hidden=false;
      cancel.addEventListener('click',()=>{
        if (!confirm('入力をやめますか？ 入力中の変更は保存されません。園に登録済みの情報はそのまま残ります。')) return;
        view.innerHTML='<h1>入力を終了しました</h1><p>園への提出は行っていません。登録済みの情報はそのまま残ります。再開する場合は招待リンクからお進みください。</p>';
      });
    }
    form.addEventListener('submit',event=>{
      event.preventDefault();
      let required=fields.filter(f=>f.required);
      if(kind.value==='new' && fields.some(f=>f.name.startsWith('g2_') && f.value.trim())) required=required.concat(fields.filter(f=>['g2_last_name','g2_first_name','g2_relationship'].includes(f.name)));
      const invalid=required.filter(f=>!f.value.trim());
      invalid.forEach(f=>f.classList.add('invalid'));
      if(invalid.length){message('必須項目を入力してください。入力内容は保持しています。');invalid[0].focus();return;}
      if(kind.value==='new' && (form.elements.birth_date.value>new Date().toISOString().slice(0,10) || form.elements.enrollment_date.value<form.elements.birth_date.value)){message('生年月日と入園予定日の前後関係を確認してください。');return;}
      submitted=Object.fromEntries(new FormData(form));
      view.innerHTML='<h1>初回入力を受け付けました</h1><p>園が確認して承認すると、パスワード設定の案内メールが届きます。</p><p class="muted">確認用：このモックでは保存・メール送信をしていません。</p><button type="button" class="secondary" id="try-review">確認用：園側の提出内容を見る</button>';
      view.querySelector('#try-review').addEventListener('click',renderReview);
      view.scrollIntoView({block:'start'});
    });
  }
  function renderReview(){
    const labels={...fixture.child_fields};
    for(const n of [1,2]) for(const [key,label] of Object.entries(fixture.guardian_fields)) labels['g'+n+'_'+key]='保護者'+(n===1?'':n)+'・'+label;
    view.innerHTML='<h1>提出内容の確認</h1><p>対象：見本 はる さん／招待先：aoi@example.invalid</p><p>本人の入力内容を確認し、園が承認してから台帳へ反映します。</p><dl class="mock-review">'+Object.entries(submitted).map(([key,value])=>'<div><dt>'+escape(labels[key]||key)+'</dt><dd>'+escape(value||'未入力')+'</dd></div>').join('')+'</dl><form method="dialog" novalidate><label>確認理由<textarea name="reason" rows="2" required></textarea></label><label class="review-confirm"><input type="checkbox" name="enrollment_confirmed">招待先・保護者と園児の対応・入力内容を確認しました。</label><div class="form-actions"><button name="decision" value="approve">承認</button><button name="decision" value="reject" class="secondary">却下</button></div></form><p class="business-note muted">園側の確認部分の抜粋です。実際の台帳更新・通知は行いません。</p>';
    view.querySelector('form').addEventListener('submit',event=>{
      event.preventDefault();const form=event.currentTarget;const approve=event.submitter.value==='approve';
      if(!form.elements.reason.value.trim()){message('確認理由を入力してください。');return;}
      if(approve && !form.elements.enrollment_confirmed.checked){message('招待先と本人・園児の対応を確認し、チェックを入れてください。');return;}
      view.innerHTML='<h1>'+(approve?'承認しました（確認用）':'却下しました（確認用）')+'</h1><p class="muted">実際の登録情報・閲覧権限は変更せず、メールも送信していません。</p>';
    });
  }
  kind.addEventListener('change',renderInput);
  state.addEventListener('change',renderInput);
  document.querySelector('#start-over').addEventListener('click',renderInput);
  renderInput();
})();
