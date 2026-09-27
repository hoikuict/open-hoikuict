(() => {
  const dialog = document.getElementById('roster-detail');
  if (!dialog) return;
  document.querySelector('.attendance-compact').addEventListener('click', event => {
    const name = event.target.closest('.name-button');
    if (!name || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    event.preventDefault();
    document.getElementById('roster-detail-name').textContent = name.dataset.name;
    dialog.querySelectorAll('[data-detail]').forEach(element => { element.textContent = name.dataset[element.dataset.detail]; });
    dialog.querySelector('[data-detail-link=checks]').href = name.href;
    dialog.querySelector('[data-detail-link=contact]').href = name.dataset.contactUrl;
    dialog.querySelector('[data-detail-link=records]').href = `/children/${name.dataset.childId}/records`;
    const memo = dialog.querySelector('[data-detail-link=memo]');
    if (memo) memo.href = `/children/${name.dataset.childId}/records/new`;
    dialog.showModal();
  });
})();
