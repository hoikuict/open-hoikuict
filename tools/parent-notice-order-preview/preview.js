/* Standalone in-memory mock. No API, database, browser storage, or business submission. */
(() => {
  const data = window.PREVIEW_DATA;
  const $ = id => document.getElementById(id);
  let items = structuredClone(data.items);
  let currentPage = 'home';
  let selectedDate = '2026-09-27';
  let detailId = null;
  let errorId = null;
  let feedbackTimer;

  function feedback(message) {
    $('feedback').textContent = message;
    $('feedback').hidden = false;
    clearTimeout(feedbackTimer);
    feedbackTimer = setTimeout(() => { $('feedback').hidden = true; }, 4500);
  }

  function sorted(page) {
    const list = $('state').value === 'none' ? [] : [...items];
    if ($('order').value === 'current') {
      if (page === 'home') return list.sort((a, b) => b.at.localeCompare(a.at));
      return list.sort((a, b) => {
        const category = Number(b.kind === 'parent_notification') - Number(a.kind === 'parent_notification');
        if (category) return category;
        // SQLite stores the deployed priority enum as normal/high, ordered DESC.
        if (a.kind === 'notice' && a.important !== b.important) return Number(a.important) - Number(b.important);
        return b.at.localeCompare(a.at);
      });
    }
    return list.sort((a, b) => {
      const stateOrder = Number(a.read) - Number(b.read);
      return stateOrder || b.at.localeCompare(a.at);
    });
  }

  function annotateLinks() {
    $('screen').querySelectorAll('a').forEach(link => {
      const item = items.find(value => link.getAttribute('href') === value.url);
      if (item) {
        link.dataset.noticeId = item.id;
        link.dataset.read = String(item.read);
        link.dataset.date = item.at;
      }
    });
  }

  function render() {
    $('page').value = currentPage === 'attention' ? 'home' : currentPage;
    $('priority').disabled = true;
    $('order-note').textContent = $('order').value === 'current'
      ? (currentPage === 'home' ? '現行ホーム：新しい日時順に5件表示。既読・未読による優先は配備コード上ありません。' : '現行一覧：出欠確認が先。その後に通常のお知らせが並びます。')
      : '変更案：未読を先に表示 → 未読・既読それぞれの中で日時の新しい順。出欠確認も同じ並びに含めます。';
    if (errorId) {
      $('screen').innerHTML = '<div class="rounded-xl border border-rose-200 bg-rose-50 p-6"><h1 class="text-xl font-bold text-rose-800">お知らせを開けませんでした（モック）</h1><p class="mt-2">既読状態は変わっていません。</p><button id="retry" class="mt-4 rounded bg-indigo-600 px-4 py-2 text-white">もう一度開く</button><button id="cancel-error" class="ml-2 rounded border px-4 py-2">戻る</button></div>';
      return;
    }
    if (detailId) {
      $('screen').innerHTML = items.find(item => item.id === detailId).detail;
      $('screen').querySelector('a').textContent = currentPage === 'home' ? 'ホームへ戻る' : '一覧へ戻る';
      $('screen').querySelector('a').dataset.back = 'true';
      return;
    }
    $('screen').innerHTML = currentPage === 'home' ? data.pages[$('contact').value] : data.pages.notices;
    const empty = '<div class="rounded-xl border border-dashed border-gray-300 bg-white p-6 text-sm text-gray-400">表示できるお知らせはありません。</div>';
    let updates = sorted(currentPage);
    if (currentPage === 'attention') {
      updates = updates.filter(item => !item.read);
      $('screen').querySelector('h1').textContent = '未読・未回答';
    }
    if (currentPage === 'home') {
      const host = $('screen').querySelector('#notice-section .space-y-3');
      host.innerHTML = updates.slice(0, 5).map(item => item.cards[String(item.read)].home).join('') || empty;
      const count = $('screen').querySelector('a[href="/parent-portal/attention"] .text-2xl');
      count.textContent = $('state').value === 'none' ? 0 : items.filter(item => !item.read).length;
      $('screen').querySelector('input[type="date"]').value = selectedDate;
      const welcome = $('screen').querySelector('h1').nextElementSibling;
      welcome.textContent = `${selectedDate} の連絡状況を確認できます。`;
    } else {
      $('screen').querySelector('.space-y-4').innerHTML = updates.map(item => item.cards[String(item.read)].list).join('') || empty;
    }
    annotateLinks();
  }

  function openItem(id) {
    if ($('error').checked) {
      $('error').checked = false;
      errorId = id;
    } else {
      const item = items.find(item => item.id === id);
      item.read = true;
      detailId = id;
      errorId = null;
    }
    render();
    window.scrollTo(0, 0);
  }

  document.addEventListener('click', event => {
    const link = event.target.closest('a');
    if (link) {
      event.preventDefault();
      const item = items.find(value => value.url === link.getAttribute('href'));
      if (item) return openItem(item.id);
      const href = link.getAttribute('href');
      if (link.dataset.back) {
        detailId = null;
      } else if (href === '/parent-portal/' || href === '/parent-portal/notices' || href === '/parent-portal/attention') {
        currentPage = href === '/parent-portal/' ? 'home' : href.endsWith('attention') ? 'attention' : 'notices';
        detailId = null;
        errorId = null;
      } else {
        feedback('このリンク先は今回の並び順モックの対象外です。');
        return;
      }
      document.querySelector('nav details').open = false;
      render();
    }
    if (event.target.id === 'retry') openItem(errorId);
    if (event.target.id === 'cancel-error') { errorId = null; render(); }
  });
  document.addEventListener('submit', event => {
    event.preventDefault();
    const dateInput = event.target.querySelector('input[type="date"]');
    if (dateInput) {
      if (!dateInput.value) return feedback('日付を入力してください。');
      selectedDate = dateInput.value;
      render();
      feedback('日付を切り替えました。連絡状況は架空の見本です。');
    } else feedback('確認用モックでは送信しません。');
  });
  for (const id of ['page', 'order', 'priority', 'contact']) {
    $(id).addEventListener('change', () => {
      if (id === 'page') currentPage = $('page').value;
      detailId = errorId = null;
      render();
    });
  }
  $('state').addEventListener('change', () => {
    items = structuredClone(data.items);
    if ($('state').value === 'filled') items.forEach(item => { item.read = true; });
    if ($('state').value === 'empty') items.forEach(item => { item.read = false; });
    detailId = errorId = null;
    render();
  });
  $('reset').addEventListener('click', () => {
    items = structuredClone(data.items);
    $('state').value = $('contact').value = 'partial';
    $('error').checked = false;
    detailId = errorId = null;
    selectedDate = '2026-09-27';
    render();
  });
  render();
})();
