(() => {
  'use strict';

  // The confirmation forms also work as inline disclosures without dialog support.
  for (const details of document.querySelectorAll('[data-review-confirm]')) {
    const dialog = document.createElement('dialog');
    if (typeof dialog.showModal !== 'function') continue;
    const summary = details.querySelector('summary');
    const form = details.querySelector('form');
    const close = form.querySelector('[data-review-close]');
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = summary.className;
    trigger.textContent = summary.textContent;
    trigger.setAttribute('aria-haspopup', 'dialog');
    dialog.className = 'daily-plan-dialog';
    dialog.setAttribute('aria-labelledby', form.querySelector('h2').id);
    dialog.append(form);
    close.hidden = false;
    close.addEventListener('click', () => dialog.close());
    trigger.addEventListener('click', () => {
      form.reset();
      form.querySelector('[data-review-error]').hidden = true;
      if (form.elements.reason) form.elements.reason.setCustomValidity('');
      dialog.showModal();
      (form.elements.reason || close).focus();
    });
    details.replaceWith(trigger, dialog);
  }

  const editor = document.querySelector('form[data-daily-plan-edit]');
  let leaving = false;
  if (editor) {
    function editValues() {
      const data = new FormData(editor);
      data.delete('csrf_token');
      return JSON.stringify(Array.from(data));
    }
    const saved = editValues();
    window.addEventListener('beforeunload', event => {
      if (!leaving && editValues() !== saved) {
        event.preventDefault();
        event.returnValue = '';
      }
    });
  }

  for (const form of document.querySelectorAll('form[data-daily-plan-form]')) {
    const error = form.querySelector('[data-review-error]');
    const reason = form.elements.reason;
    const comment = form.elements.comment;
    reason?.addEventListener('input', () => reason.setCustomValidity(''));
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (form.getAttribute('aria-busy') === 'true') return;
      const button = event.submitter;
      if (reason && !reason.value.trim()) {
        reason.setCustomValidity('修正に戻す理由を入力してください。');
        reason.reportValidity();
        return;
      }
      if (button?.value === 'rejected' && !comment.value.trim()) {
        error.textContent = '差戻し理由を入力してください。';
        error.hidden = false;
        comment.focus();
        return;
      }
      const data = new FormData(form);
      if (button?.name) data.set(button.name, button.value);
      form.setAttribute('aria-busy', 'true');
      const buttons = Array.from(form.querySelectorAll('button:not(:disabled)'));
      buttons.forEach(control => { control.disabled = true; });
      const dialog = form.closest('dialog');
      const preventCancel = event => event.preventDefault();
      dialog?.addEventListener('cancel', preventCancel);
      error.hidden = true;
      try {
        const response = await fetch(form.action, {
          method: 'POST',
          body: data,
          credentials: 'same-origin',
          headers: {
            Accept: 'application/json',
            'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.content || ''
          }
        });
        const result = await response.json().catch(() => null);
        if (!response.ok && typeof result?.detail === 'string') throw new Error(result.detail);
        if (!response.ok || result?.document_id !== Number(form.dataset.dailyPlanForm)) {
          throw new Error('処理結果を確認できませんでした。日案を開き直して状態を確認してください。');
        }
        leaving = true;
        const detail = '/plans/documents/' + result.document_id;
        if (location.pathname === detail) {
          history.replaceState(history.state, '', detail + '#review-status');
          location.reload();
        } else {
          location.assign(detail + '#review-status');
        }
      } catch (exception) {
        error.textContent = exception instanceof TypeError
          ? '通信結果を確認できませんでした。接続を確認し、別のタブで日案の状態を確認してください。'
          : exception.message;
        error.hidden = false;
        error.focus();
      } finally {
        dialog?.removeEventListener('cancel', preventCancel);
        form.removeAttribute('aria-busy');
        buttons.forEach(control => { control.disabled = false; });
      }
    });
  }
})();
