(() => {
  'use strict';
  const fixture = window.ParentGuardianFixture;
  const view = document.querySelector('#mock-view');
  const kind = document.querySelector('#preview-kind');
  const state = document.querySelector('#preview-state');
  let submitted = null;
  const isProposed = () => ['add', 'invite'].includes(kind.value);
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function message(text) {
    let error = view.querySelector('[role=alert]');
    if (!error) { error = document.createElement('p'); error.className = 'error'; error.setAttribute('role','alert'); view.querySelector('h1').after(error); }
    error.textContent = text; error.scrollIntoView({block:'center'});
  }
  function renderInput() {
    submitted = null;
    document.querySelector('#preview-scope').textContent = isProposed()
      ? '提案：保護者本人の9項目（必須6・任意3）。園児・家族共通情報は変更しません。'
      : '比較用：現行版の入力項目と必須条件をそのまま再現しています。';
    if (state.value === 'expired') {
      view.innerHTML = '<h1>入力時間を過ぎました</h1><p role="alert" class="error">招待リンクから手続きをやり直してください。リンクも期限切れの場合は園へ再招待を依頼してください。</p><p class="muted">この表示は確認用です。実際の登録や取消は行いません。</p>'; return;
    }
    view.innerHTML = fixture.views[kind.value];
    const form = view.querySelector('form');
    const fields = [...form.querySelectorAll('input[name],textarea[name]')];
    for (const field of fields) {
      const populated = ['filled','error'].includes(state.value) || (state.value === 'partial' && ['g1_last_name','g1_first_name','g1_last_name_kana','g1_first_name_kana','g1_relationship'].includes(field.name));
      field.value = populated ? (fixture.sample[field.name] || '') : '';
      if (!isProposed() && ['last_name','first_name'].includes(field.name) && state.value !== 'filled') field.value = fixture.sample[field.name];
      field.addEventListener('input', () => field.classList.remove('invalid'));
    }
    const childIdFields = ['birth_date','enrollment_date','last_name_kana','first_name_kana','home_address'];
    if (state.value === 'error') {
      const phone = form.querySelector('[name=g1_phone]'); phone.value = ''; phone.classList.add('invalid');
      message('電話番号を入力してください。入力したほかの項目は保持しています。');
    }
    const cancel = document.createElement('button'); cancel.type='button'; cancel.className='secondary'; cancel.textContent='入力をやめる'; cancel.id='cancel-input';
    form.append(' ',cancel);
    cancel.addEventListener('click', () => {
      if (!confirm('入力をやめますか？ 入力中の内容は保存されません。')) return;
      view.innerHTML='<h1>入力を終了しました</h1><p>園への提出は行っていません。再開する場合は招待リンクからお進みください。</p>';
    });
    form.addEventListener('submit', event => {
      event.preventDefault();
      let required = fields.filter(field => field.required);
      if (kind.value === 'new' && fields.some(f => f.name.startsWith('g2_') && f.value.trim())) {
        required = required.concat(fields.filter(f => ['g2_last_name','g2_first_name','g2_relationship'].includes(f.name)));
      }
      const invalid = required.filter(field => !field.value.trim());
      invalid.forEach(field => field.classList.add('invalid'));
      if (invalid.length) { message('必須項目を入力してください。入力内容は保持しています。'); invalid[0].focus(); return; }
      if (!isProposed() && childIdFields.some(name => !form.elements[name].value)) { message('園児の情報を入力してください。'); return; }
      if (!isProposed() && (form.elements.birth_date.value > new Date().toISOString().slice(0,10) || form.elements.enrollment_date.value < form.elements.birth_date.value)) { message('生年月日と入園予定日の前後関係を確認してください。'); return; }
      submitted = Object.fromEntries(new FormData(form));
      view.innerHTML='<h1>初回入力を受け付けました</h1><p>園が確認して承認すると、パスワード設定の案内メールが届きます。</p><p class="muted">このモックでは保存・メール送信をしていません。</p><button type="button" id="try-review" class="secondary">確認用：園側の提出内容を見る</button>';
      view.querySelector('#try-review').addEventListener('click',renderReview);
      view.scrollIntoView({block:'start'});
    });
  }
  function renderReview() {
    const labels = {...fixture.child_fields};
    for (const n of [1,2]) for (const [key,label] of Object.entries(fixture.guardian_fields)) labels['g'+n+'_'+key] = (isProposed() ? '保護者・' : '保護者'+n+'・')+label;
    const scope = isProposed() ? '在園児の保護者登録' : (kind.value === 'new' ? '新規入園の初回入力' : '初回入力の依頼');
    view.innerHTML = '<h1>提出内容の確認</h1><p>'+scope+'：見本 はる さん</p><p>招待先：aoi@example.invalid</p><p>'+ (isProposed() ? '保護者本人の情報だけを反映します。園児・家族共通情報は変更しません。' : '比較用：現行の提出内容の一覧です。') +'</p><dl class="mock-review">'+Object.entries(submitted).map(([key,value])=>'<div><dt>'+escape(labels[key]||key)+'</dt><dd>'+escape(value||'未入力')+'</dd></div>').join('')+'</dl><form id="review-form" method="dialog" novalidate><label>確認理由<textarea name="reason" rows="2" required placeholder="照合内容と確認方法を記録してください"></textarea></label><label class="review-confirm"><input type="checkbox" name="enrollment_confirmed">招待先・保護者と園児の対応・入力内容を確認しました。承認すると対象園児の閲覧を許可します。</label><div class="form-actions"><button name="decision" value="approve">承認</button><button name="decision" value="reject" class="secondary">却下</button></div></form><p class="business-note muted">確認用：園側の申請確認部分を抜粋したモックです。実際の承認・却下・通知は行いません。</p>';
    view.querySelector('form').addEventListener('submit', event => {
      event.preventDefault();
      const form=event.currentTarget;
      const approved=event.submitter.value==='approve';
      if (!form.elements.reason.value.trim()) {message('確認理由を入力してください。');return;}
      if (approved && !form.elements.enrollment_confirmed.checked) {message('招待先と本人・園児の対応を確認し、チェックを入れてください。');return;}
      view.innerHTML='<h1>'+ (approved ? '承認しました（確認用）' : '却下しました（確認用）') +'</h1><p>'+ (approved ? '本人用のパスワード設定案内へ進みます。' : '入力内容を確認し、必要に応じて園から再招待します。') +'</p><p class="muted">実際の台帳・閲覧権限は変更せず、メールも送信していません。</p>';
    });
    view.scrollIntoView({block:'start'});
  }
  kind.addEventListener('change',renderInput);
  state.addEventListener('change',renderInput);
  document.querySelector('#start-over').addEventListener('click',renderInput);
  renderInput();
})();
