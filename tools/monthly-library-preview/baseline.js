document.addEventListener('submit', event => { event.preventDefault(); alert('現行画面の表示見本です。操作は「変更案に戻る」から試せます。'); });
document.querySelectorAll('a[href^="/plans/"]').forEach(link => link.addEventListener('click', event => { event.preventDefault(); alert('既存の業務画面へのリンクです。モックからは移動しません。'); }));
