(() => {
  'use strict';
  const root = document.getElementById('guardian-terminal');
  if (!root) return;
  const startUrl = '/guardian/terminal';
  const ready = root.dataset.ready === '1';
  const active = root.dataset.active === '1';
  const idleMs = Number(root.dataset.idleSeconds) * 1000;
  let lastActivity = Date.now();
  let available = navigator.onLine;
  let checking = false;
  let recheckPending = false;
  let submitting = false;
  let resetPending = false;
  let wakeLock = null;
  const connection = document.getElementById('terminal-connection');
  const warning = document.getElementById('terminal-warning');
  const idleWarning = document.getElementById('terminal-idle-warning');
  const token = document.querySelector('meta[name="csrf-token"]')?.content || '';

  document.querySelectorAll('form[method="post" i]').forEach(form => {
    if (!form.querySelector('[name="csrf_token"]')) {
      const input = document.createElement('input');
      input.type = 'hidden'; input.name = 'csrf_token'; input.value = token;
      form.appendChild(input);
    }
  });

  const reset = () => {
    if (!navigator.onLine || !available) {
      resetPending = true;
      document.querySelector('main').hidden = true;
      idleWarning.hidden = true;
      return;
    }
    window.location.replace(startUrl);
  };
  const activity = () => { lastActivity = Date.now(); idleWarning.hidden = true; };
  ['pointerdown', 'keydown', 'input', 'scroll'].forEach(name => document.addEventListener(name, activity, { passive: true }));
  document.getElementById('terminal-continue').addEventListener('click', activity);

  function showAvailability(ok, message = '') {
    available = ok;
    connection.textContent = ok ? '接続済み' : '接続を確認してください';
    warning.hidden = ok;
    document.getElementById('terminal-warning-message').textContent = message;
    document.querySelectorAll('form[method="post" i] button[type="submit"]').forEach(button => {
      if (!ok && !button.disabled) { button.dataset.connectionDisabled = '1'; button.disabled = true; }
      if (ok && button.dataset.connectionDisabled === '1') { button.disabled = false; delete button.dataset.connectionDisabled; }
    });
  }

  async function checkConnection() {
    if (!ready || checking || submitting) return;
    checking = true;
    const previouslyAvailable = available;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/guardian/terminal/status', { cache: 'no-store', redirect: 'error', signal: controller.signal });
      if (!response.ok) throw new Error('Device or connection unavailable');
      const status = await response.json();
      if (submitting) return;
      if (!navigator.onLine) throw new Error('Connection was lost during the check');
      if (status.kiosk !== true) throw new Error('Unexpected response');
      if (status.today !== root.dataset.today || !previouslyAvailable || !available || resetPending) {
        available = true;
        reset();
        return;
      }
      showAvailability(true);
    } catch (_) {
      if (submitting) return;
      showAvailability(false, '通信または端末登録を確認できません。打刻は送信されません。職員にお知らせください。');
    } finally {
      clearTimeout(timeout);
      checking = false;
      if (recheckPending && navigator.onLine) {
        recheckPending = false;
        checkConnection();
      }
    }
  }

  const reconnect = () => {
    if (ready) {
      if (checking) recheckPending = true;
      else checkConnection();
    }
    else { available = navigator.onLine; reset(); }
  };
  document.getElementById('terminal-retry').addEventListener('click', reconnect);
  window.addEventListener('offline', () => showAvailability(false, '通信が切れています。打刻は送信されません。職員にお知らせください。'));
  window.addEventListener('online', reconnect);
  // A failed submission is never queued or automatically sent again.
  document.addEventListener('submit', event => {
    if (event.defaultPrevented || event.target.method.toLowerCase() !== 'post') return;
    if (!navigator.onLine || !available || submitting) { event.preventDefault(); return; }
    submitting = true;
  });

  async function keepScreenAwake() {
    if (!('wakeLock' in navigator) || wakeLock || document.visibilityState !== 'visible') return;
    try {
      wakeLock = await navigator.wakeLock.request('screen');
      wakeLock.addEventListener('release', () => { wakeLock = null; });
    } catch (_) { /* Device power settings remain available when wake lock is unsupported. */ }
  }
  document.getElementById('terminal-fullscreen').addEventListener('click', async () => {
    try {
      if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
      else await document.exitFullscreen();
    } catch (_) { /* The Chromebook fullscreen key can also be used. */ }
    keepScreenAwake();
  });
  document.addEventListener('fullscreenchange', () => {
    document.getElementById('terminal-fullscreen').textContent = document.fullscreenElement ? '全画面を終了' : '全画面';
  });
  window.addEventListener('pageshow', event => { if (event.persisted && active) reset(); });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    if (active && Date.now() - lastActivity >= idleMs) { reset(); return; }
    checkConnection();
    keepScreenAwake();
  });
  if (ready) {
    if (!available) showAvailability(false, '通信が切れています。職員にお知らせください。');
    checkConnection();
    keepScreenAwake();
    setInterval(checkConnection, 30000);
    setInterval(() => {
      if (!active || submitting || resetPending) return;
      const remaining = Math.ceil((idleMs - (Date.now() - lastActivity)) / 1000);
      if (remaining <= 0) { reset(); return; }
      idleWarning.hidden = remaining > 15;
      document.getElementById('terminal-idle-message').textContent = `あと${remaining}秒で最初の画面に戻ります。`;
    }, 1000);
  }
})();
