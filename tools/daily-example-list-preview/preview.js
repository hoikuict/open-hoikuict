/* Synthetic, browser-memory-only mock. No fetch, storage, or form submission. */
(() => {
  const activities = [
    ['秋の風を感じる園庭散歩', '戸外の心地よさを感じ、保育者と一緒に身近な自然に親しむ。', '園庭で風や葉の動きに気づき、指差しや声に保育者が応じながら過ごす。'],
    ['布の感触を楽しむ室内遊び', 'やわらかな布に触れ、身近な大人とのやり取りを楽しむ。', '大きな布を触ったり、保育者といないいないばあをしたりして遊ぶ。'],
    ['マットで体を動かす', '自分のペースで体を動かす心地よさを味わう。', '平らなマットの上で寝返りやはいはいなど、それぞれの動きを楽しむ。'],
    ['絵本とわらべうた', '親しみのある声やリズムに安心して耳を傾ける。', '少人数で絵本を見たり、保育者の歌に合わせて触れ合ったりする。'],
    ['園庭の落ち葉を眺める', '秋の色や動きに関心を向け、保育者と楽しさを共有する。', '葉が動く様子を保育者と眺め、子どもの表情や指差しに応じる。'],
    ['大きなボールで遊ぶ', '目で追ったり手を伸ばしたりして、物の動きを楽しむ。', '転がるボールを保育者と一緒に追いかけ、触れて遊ぶ。'],
    ['音の出る玩具を楽しむ', '自分の働きかけで音が変わることに気づく。', '年齢に合った大きさの玩具を振ったり鳴らしたりして、音の変化を楽しむ。'],
    ['秋の風を感じる園庭散歩と、雨天時の室内遊び（布やマットを使って、一人ひとりのペースで過ごす）', 'その日の体調や気分に合わせ、安心して好きな遊びを楽しむ。', '天候を見ながら園庭または室内を選び、落ち着いて遊べる場所を用意する。'],
    ['保育者との触れ合い遊び', '応答的な関わりの中で、安心して気持ちを表す。', '子どもの声や表情に応じ、手遊びや歌を繰り返し楽しむ。'],
    ['好きな玩具を選んで遊ぶ', '気になる物を見つけ、自分から関わる楽しさを感じる。', '手に取りやすい位置に玩具を置き、興味の向く遊びを見守る。'],
  ];
  const makeRows = (activity, index) => [
    ['随時／登園', '保育者に抱かれたり、安心できる場所で遊んだりする。', '家庭での様子を聞き、一人ひとりの表情や体調を確認する。', '落ち着ける場所と玩具を用意する。'],
    ['9:00／室内遊び', '気になる玩具へ手を伸ばして遊ぶ。', '視線や動きに応じながら、遊びを見守る。', '十分に動ける広さを確保する。'],
    ['9:30／水分・身支度', '声をかけてもらいながら、身支度をする。', '生活のペースに合わせて、ゆったり関わる。', '体調や気分に合わせて無理なく進める。'],
    [`10:00／${activity}`, index % 2 ? '保育者の声に笑顔を見せ、繰り返し遊ぼうとする。' : '周囲を見たり、気になる物へ手を伸ばしたりする。', '興味を言葉にして受け止め、十分に試せる時間をつくる。', '活動場所と用具を確認し、個々の姿に応じて関わる。'],
    ['10:40／休息・着替え', '保育者と一緒に落ち着いて過ごす。', '気持ちを受け止め、ゆっくり次の活動へ誘う。', '衣服や室内環境を整える。'],
    ['11:00／食事', '保育者と関わりながら食事をとる。', '一人ひとりのペースに合わせて援助する。', '個別の食事内容と提供方法を確認する。'],
    ['12:00／午睡・休息', '安心できる関わりの中で休む。', '眠りや休息のペースに応じて関わる。', '園の手順に沿って継続して様子を確認する。'],
    ['15:00／目覚め・おやつ', '目覚めた子からゆったりと過ごす。', '機嫌や体調を確認し、一人ひとりに応じる。', '落ち着いて食べられる環境を整える。'],
    ['16:00／遊び・降園', '好きな遊びをしながら迎えを待つ。', '一日の様子を保護者へ伝える。', '職員間で必要な引き継ぎを行う。'],
  ];
  const examples = activities.map(([activity, aim, content], index) => ({
    id: `fictional-${index + 1}`, title: `架空の日案例 ${String(index + 1).padStart(2, '0')}`,
    activity, aim, content, age: '0歳児', month: '10', rows: makeRows(activity, index),
  }));
  const $ = (selector, root = document) => root.querySelector(selector);
  const all = (selector, root = document) => [...root.querySelectorAll(selector)];
  const list = $('#activity-list'), search = $('#example-search'), draft = $('#daily-draft');
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let saved = null;
  function notify(text) { $('#mock-status').textContent = text; $('#mock-status').hidden = false; }
  function clearValidation() {
    $('#mock-validation').hidden = true;
    all('[aria-invalid]', draft).forEach(input => input.removeAttribute('aria-invalid'));
  }
  function renderExamples() {
    const mode = $('#mock-results').value;
    const query = $('[name=q]', search).value.trim().toLowerCase();
    const age = $('[name=age_class]', search).value, month = $('[name=month]', search).value;
    const matches = mode === 'normal' ? examples.filter(e => (!age || e.age === age) && e.month === month &&
      (!query || JSON.stringify(e).toLowerCase().includes(query))) : [];
    $('#result-count').textContent = `主な活動　${matches.length}件`;
    $('#no-examples').hidden = !!matches.length || mode === 'error';
    $('#corpus-error').hidden = mode !== 'error';
    list.hidden = !matches.length;
    list.innerHTML = matches.map(e => `<details class="activity-card" data-example="${e.id}">
      <summary class="activity-summary"><span class="main-activity">${escape(e.activity)}</span><span class="age-month">${e.age} / ${e.month}月</span><span class="activity-toggle" aria-hidden="true"></span></summary>
      <div class="activity-detail"><div class="detail-heading"><span>${escape(e.title)}</span><span>時系列 ${e.rows.length}行</span></div>
      <div class="detail-purpose"><section><h3>ねらい</h3><p>${escape(e.aim)}</p></section><section><h3>内容</h3><p>${escape(e.content)}</p></section></div>
      <div class="daily-plan-grid-scroll daily-plan-grid-preview"><table class="daily-plan-edit-grid"><thead><tr><th>時間</th><th>子どもの様子</th><th>保育士の援助</th><th>配慮事項</th></tr></thead><tbody>${e.rows.map(row => `<tr>${row.map(cell => `<td>${escape(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
      <div class="detail-actions"><button type="button" class="button button--primary" data-copy="${e.id}">この候補を下書きへコピー</button><button type="button" class="button button--ghost" data-close>詳細を閉じる</button></div></div></details>`).join('');
  }
  function setRows(rows) {
    const body = $('#daily-timeline-rows'); body.replaceChildren();
    rows.forEach((row, index) => {
      const node = $('#daily-row-template').content.firstElementChild.cloneNode(true);
      $('[name=timeline_row_key]', node).value = `mock-${index}`;
      ['timeline_time','timeline_children','timeline_support','timeline_considerations'].forEach((name, i) => $(`[name=${name}]`, node).value = row[i] || '');
      body.append(node);
    });
  }
  function fillExample(example) {
    $('[name=example_id]', draft).value = example.id;
    $('[name=example_source_ref]', draft).value = 'fictional-preview';
    $('[name=daily_aims]', draft).value = example.aim;
    $('[name=daily_content]', draft).value = example.content;
    setRows(example.rows); clearValidation();
  }
  function applyState(state) {
    saved = null; clearValidation(); $('#mock-status').hidden = true;
    $('[name=target_date]', draft).value = '2026-10-11';
    $('[name=age_class]', draft).value = '0歳児';
    $('[name=classroom_ref]', draft).value = 'ことり組（架空）';
    $('[name=owner_name]', draft).value = '確認用の職員';
    ['daily_aims','daily_content','example_id','example_source_ref'].forEach(name => $(`[name=${name}]`, draft).value = '');
    setRows([['','','','']]);
    if (state === 'filled' || state === 'error') fillExample(examples[0]);
    if (state === 'partial') {
      $('[name=daily_aims]', draft).value = '安心して保育者と関わりながら遊ぶ。';
      setRows([['9:00／室内遊び','気になる玩具へ手を伸ばす。','',''],['10:00','','','']]);
    }
    if (state === 'error') { $('[name=target_date]', draft).value = ''; showErrors(); }
  }
  function showErrors() {
    const errors=[];
    for (const [name,label] of [['target_date','対象日'],['age_class','年齢']]) {
      const input=$(`[name=${name}]`, draft);
      if (!input.value) { input.setAttribute('aria-invalid','true'); errors.push(`${label}を入力してください`); }
    }
    $('#mock-validation').hidden = errors.length === 0;
    $('#validation-message').textContent = errors.join('。');
    return errors.length > 0;
  }
  function snapshot() { return JSON.stringify([...new FormData(draft).entries()]); }
  search.addEventListener('submit', event => { event.preventDefault(); renderExamples(); });
  list.addEventListener('click', event => {
    const close = event.target.closest('[data-close]');
    if (close) { const card = close.closest('details'); card.open = false; $('summary', card).focus(); return; }
    const copy = event.target.closest('[data-copy]');
    if (!copy) return;
    fillExample(examples.find(e => e.id === copy.dataset.copy));
    notify('候補を下書きへコピーしました。内容を編集し、「下書きを保存」で保存を試せます。');
    draft.scrollIntoView({behavior:'instant',block:'start'});
    $('[name=daily_aims]', draft).focus({preventScroll:true});
  });
  draft.addEventListener('submit', event => {
    event.preventDefault(); clearValidation();
    if (showErrors()) { $('#mock-validation').scrollIntoView({block:'center'}); return; }
    saved = snapshot(); notify('このモック内で下書きを保存しました。本番への保存は行っていません。');
    $('#mock-status').scrollIntoView({block:'center'});
  });
  draft.addEventListener('input', () => { if (saved && snapshot() !== saved) notify('保存後の変更があります。このモック内でも、変更を反映するにはもう一度保存してください。'); });
  $('#mock-state').addEventListener('change', event => applyState(event.target.value));
  $('#mock-results').addEventListener('change', renderExamples);
  $('#reset-mock').addEventListener('click', () => {
    $('#mock-state').value = 'empty'; $('#mock-results').value = 'normal';
    $('[name=age_class]', search).value = '0歳児'; $('[name=month]', search).value = '10'; $('[name=q]', search).value = '';
    applyState('empty'); renderExamples();
  });
  $('#mock-back').addEventListener('click', event => { event.preventDefault(); notify('確認用モックのため、他の業務画面へは移動しません。'); window.scrollTo({top:0,behavior:'instant'}); });
  renderExamples();
})();
