document.querySelectorAll('#review-controls select').forEach(select => select.addEventListener('change', () => select.form.requestSubmit()));
document.addEventListener('click', event => {
  if (event.target.closest('[data-preview-outside]')) {
    event.preventDefault();
    const feedback = document.getElementById('preview-feedback');
    feedback.hidden = false;
    feedback.scrollIntoView({behavior: 'smooth', block: 'center'});
  }
  const sidebar = document.getElementById('staff-sidebar');
  const backdrop = document.getElementById('staff-sidebar-backdrop');
  if (event.target.closest('[data-sidebar-open]')) {
    sidebar?.classList.remove('-translate-x-full');
    backdrop?.classList.remove('hidden');
  }
  if (event.target.closest('[data-sidebar-close]') || event.target === backdrop) {
    sidebar?.classList.add('-translate-x-full');
    backdrop?.classList.add('hidden');
  }
});
