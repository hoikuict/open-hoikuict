  // Inserted into a served copy of the deployed UI; no production asset changes.
  const previewMatch = document.querySelector('#preview-match');
  const previewState = document.querySelector('#preview-state');
  const previewRetry = document.querySelector('#preview-retry');
  let previewError = false;
  const realPreviewApi = api;
  api = async function(path, options = {}) {
    if (path.startsWith('candidates?')) {
      path += '&preview_match=' + encodeURIComponent(previewMatch.value);
      if (previewError) path += '&preview_error=1';
    }
    return realPreviewApi(path, options);
  };
  const matchNote = document.createElement('small');
  matchNote.id = 'search-match-note';
  q('.keyword-box').append(matchNote);
  function previewDescription() {
    matchNote.textContent = previewMatch.value === 'current'
      ? '現在の動作：ひらがな・カタカナ・漢字は別々に検索します。'
      : previewMatch.value === 'related'
        ? '追加案：かなの違いをそろえ、真似・まね・模倣をまとめて検索します。'
        : '今回の案：かなの違いをそろえ、真似・まねをまとめて検索します。';
  }
  previewMatch.addEventListener('change', () => { previewDescription(); search(); });
  previewState.addEventListener('change', () => {
    commitEdit();
    previewError = previewState.value === 'error';
    previewRetry.hidden = !previewError;
    if (!previewError) {
      remember();
      const keys = Object.keys(ctx().definitions);
      const selected = previewState.value === 'filled' ? keys
        : previewState.value === 'partial' ? ['common:goal', current.field] : [];
      ctx().sheet.fields = Object.fromEntries([...new Set(selected)].map(key => [key, {
        body: key === current.field ? '【架空の手入力】身近な遊びをゆったり楽しめるようにする。'
          : '【架空の入力】' + ctx().definitions[key].label + 'の記入例です。', origins: []
      }]));
      paper(); panel();
      announce('見本の入力状態を切り替えました。「ひとつ戻す」で戻せます。');
    } else {
      search();
      announce('見本の検索エラーを表示しています。入力内容は保持しています。');
    }
  });
  previewRetry.addEventListener('click', () => {
    previewError = false; previewRetry.hidden = true; previewState.value = 'custom';
    search(); announce('検索エラーを解除しました。入力内容は保持しています。');
  });
  document.querySelectorAll('[data-preview-query]').forEach(button => button.addEventListener('click', () => {
    commitEdit();
    // The sample buttons lead to a relevant field; normal typing preserves the selected field.
    current.field = individual() && current.child ? current.child + ':play' : 'common:goal';
    keyword = button.dataset.previewQuery; mode = 'original'; q('#keyword').value = keyword;
    panel();
  }));
  root.addEventListener('input', event => {
    if (!previewError && (event.target.dataset.cell || event.target.hasAttribute('data-owner'))) previewState.value = 'custom';
  });
  current.field = current.child ? current.child + ':play' : 'common:goal';
  keyword = 'まね'; q('#keyword').value = keyword;
  previewDescription();
