  let chiefPreviewError = false;
  const chiefPreviewState = document.querySelector('#chief-preview-state');
  if (chiefPreviewState) {
  chiefPreviewState.addEventListener('change', () => {
    commitEdit();
    chiefPreviewError = chiefPreviewState.value === 'error';
    if (chiefPreviewError) {
      announce('出力エラーの見本です。印刷用PDFまたはExcel出力で確認できます。入力は保持しています。');
      return;
    }
    remember();
    const selected = chiefPreviewState.value === 'filled' ? Object.keys(ctx().definitions)
      : chiefPreviewState.value === 'partial' ? ['common:goal', current.field] : [];
    ctx().sheet.fields = Object.fromEntries([...new Set(selected)].map(key => [key, {
      body:'【架空の入力】'+ctx().definitions[key].label+'の記入例です。', origins:[]
    }]));
    paper(); panel();
    announce('見本の入力状態を切り替えました。「ひとつ戻す」で戻せます。');
  });
  root.addEventListener('input', event => {
    if (event.target.dataset.cell || event.target.hasAttribute('data-owner')) chiefPreviewState.value = 'custom';
  });
  }
