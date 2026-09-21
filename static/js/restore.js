(() => {
  document.querySelectorAll('[data-restore-form]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (form.dataset.submitting === '1') { event.preventDefault(); return; }
      form.dataset.submitting = '1';
      const message = form.querySelector('[data-restore-wait]');
      if (message) message.classList.remove('hidden');
      if (event.submitter) event.submitter.disabled = true;
    });
  });
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('input[type=password]').forEach((field) => { field.value = ''; });
    document.querySelectorAll('[data-restore-form]').forEach((form) => {
      if (form.dataset.submitting === '1') {
        form.dataset.submitting = '0';
        document.querySelectorAll('button[type=submit]').forEach((button) => {
          if (button.form === form) button.disabled = false;
        });
        form.querySelector('[data-restore-wait]')?.classList.add('hidden');
      }
    });
  });
})();
