(function initGuardianTerminal() {
  'use strict';
  const root = document.getElementById('guardian-terminal');
  if (!root) return;
  window.guardianTerminalCleanup?.();
  const lifecycle = new AbortController();
  const timers = [];
  let disposed = false;
  const listen = (target, type, fn, options = {}) => target.addEventListener(type, fn, { ...options, signal: lifecycle.signal });
  const repeat = (fn, ms) => timers.push(setInterval(fn, ms));
  window.guardianTerminalCleanup = () => {
    disposed = true;
    lifecycle.abort();
    timers.forEach(clearInterval);
    wakeLock?.release().catch(() => {});
  };
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
    navigate(startUrl);
  };
  async function navigate(url, options = {}) {
    if (submitting || disposed) return;
    submitting = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(url, { ...options, cache: 'no-store', signal: controller.signal });
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const next = page.getElementById('guardian-terminal');
      if (!next || new URL(response.url).origin !== location.origin) throw new Error('Unexpected terminal response');
      const scripts = [...next.querySelectorAll('script:not([src])')].map(script => script.textContent);
      next.querySelectorAll('script').forEach(script => script.remove());
      window.guardianTerminalCleanup();
      // The fullscreen documentElement stays mounted across GETs, POSTs and redirects.
      root.innerHTML = next.innerHTML;
      for (const key of Object.keys(root.dataset)) delete root.dataset[key];
      Object.assign(root.dataset, next.dataset);
      document.title = page.title;
      document.querySelector('meta[name="csrf-token"]').content = page.querySelector('meta[name="csrf-token"]')?.content || '';
      history.replaceState(null, '', options.method === 'POST' && !response.redirected ? startUrl : response.url);
      for (const text of scripts) {
        const script = document.createElement('script');
        script.textContent = text;
        root.appendChild(script);
        script.remove();
      }
      initGuardianTerminal();
      window.scrollTo(0, 0);
    } catch (_) {
      if (disposed) return;
      submitting = false;
      showAvailability(false, options.method === 'POST'
        ? '送信結果を確認できません。自動で再送しません。接続を確認してから記録を確認してください。'
        : '画面を読み込めませんでした。接続を確認してください。');
    } finally { clearTimeout(timeout); }
  }
  listen(document, 'click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || link.target || link.download) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || !/^\/guardian(?:\/|$)/.test(url.pathname)) return;
    event.preventDefault();
    if (!navigator.onLine || !available) { showAvailability(false, '接続を確認してください。'); return; }
    navigate(url.href);
  });
  const activity = () => { lastActivity = Date.now(); idleWarning.hidden = true; };
  ['pointerdown', 'keydown', 'input', 'scroll'].forEach(name => listen(document, name, activity, { passive: true }));
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
      if (submitting || disposed) return;
      if (!navigator.onLine) throw new Error('Connection was lost during the check');
      if (status.kiosk !== true) throw new Error('Unexpected response');
      if (status.today !== root.dataset.today || !previouslyAvailable || !available || resetPending) {
        available = true;
        reset();
        return;
      }
      showAvailability(true);
    } catch (_) {
      if (submitting || disposed) return;
      showAvailability(false, '通信または端末登録を確認できません。打刻は送信されません。職員にお知らせください。');
    } finally {
      clearTimeout(timeout);
      checking = false;
      if (!disposed && recheckPending && navigator.onLine) {
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
  listen(window, 'offline', () => showAvailability(false, '通信が切れています。打刻は送信されません。職員にお知らせください。'));
  listen(window, 'online', reconnect);
  // A failed submission is never queued or automatically sent again.
  listen(document, 'submit', event => {
    if (event.defaultPrevented) return;
    const form = event.target;
    const url = new URL(form.action, location.href);
    if (url.origin !== location.origin || !/^\/guardian(?:\/|$)/.test(url.pathname)) return;
    event.preventDefault();
    if (!navigator.onLine || !available || submitting) return;
    const data = new FormData(form, event.submitter);
    if (form.method.toLowerCase() === 'post') navigate(url.href, { method: 'POST', body: data });
    else { url.search = new URLSearchParams(data).toString(); navigate(url.href); }
  });

  async function keepScreenAwake() {
    if (!('wakeLock' in navigator) || wakeLock || document.visibilityState !== 'visible') return;
    try {
      wakeLock = await navigator.wakeLock.request('screen');
      if (disposed) { await wakeLock.release(); return; }
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
  const fullscreenLabel = () => { document.getElementById('terminal-fullscreen').textContent = document.fullscreenElement ? '全画面を終了' : '全画面'; };
  listen(document, 'fullscreenchange', fullscreenLabel);
  fullscreenLabel();
  const done = document.querySelector('[data-terminal-return-url]');
  if (done) timers.push(setTimeout(() => navigate(done.dataset.terminalReturnUrl), Number(done.dataset.terminalReturnMs) || 1000));
  listen(window, 'popstate', reset);
  listen(window, 'pageshow', event => { if (event.persisted && active) reset(); });
  listen(document, 'visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    if (active && Date.now() - lastActivity >= idleMs) { reset(); return; }
    checkConnection();
    keepScreenAwake();
  });
  if (ready) {
    if (!available) showAvailability(false, '通信が切れています。職員にお知らせください。');
    checkConnection();
    keepScreenAwake();
    repeat(checkConnection, 30000);
    repeat(() => {
      if (!active || submitting || resetPending) return;
      const remaining = Math.ceil((idleMs - (Date.now() - lastActivity)) / 1000);
      if (remaining <= 0) { reset(); return; }
      idleWarning.hidden = remaining > 15;
      document.getElementById('terminal-idle-message').textContent = `あと${remaining}秒で最初の画面に戻ります。`;
    }, 1000);
  }
})();
