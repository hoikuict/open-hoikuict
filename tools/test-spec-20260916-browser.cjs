const assert = require('node:assert/strict');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const port = Number(process.env.TEST_PORT || 8771);
const base = `http://127.0.0.1:${port}`;
const python = process.env.TEST_PYTHON || (process.platform === 'win32' ? 'venv/Scripts/python.exe' : 'python');
const server = spawn(python, ['-m', 'uvicorn', 'tools.spec_20260916_browser_fixture:app', '--host', '127.0.0.1', '--port', String(port)], {
  cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', HOIKUICT_DATABASE_URL: 'sqlite://', HOIKUICT_ENV: 'development', HOIKUICT_COOKIE_SECURE: '0' },
});
let output = '';
server.stdout.on('data', data => { output += data; });
server.stderr.on('data', data => { output += data; });
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  let browser;
  try {
    let ids;
    for (let attempt = 0; attempt < 100; attempt++) {
      try { const res = await fetch(`${base}/__fixture`); if (res.ok) { ids = await res.json(); break; } } catch (_) {}
      if (server.exitCode !== null) throw new Error(output);
      await pause(100);
    }
    assert(ids, output);
    browser = await chromium.launch({ channel: process.env.TEST_BROWSER_CHANNEL || 'msedge', headless: true });
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, ignoreHTTPSErrors: true });
    await context.request.get(`${base}/__fixture_login`);
    await context.request.post(`${base}/parent-portal/login`, { form: { parent_account_id: String(ids.parent_id) } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('requestfailed', request => { if (!request.url().includes('/save')) console.error('Request failed:', request.url(), request.failure()?.errorText); });
    const noteUrl = `${base}/meeting-notes/${ids.note_id}`;
    await page.goto(noteUrl);
    await page.waitForFunction(() => document.querySelector('.ql-editor')?.getAttribute('contenteditable') === 'true', { timeout: 20000 });
    const saved = () => page.waitForFunction(() => document.getElementById('save-status').textContent.startsWith('保存済み '));
    await page.locator('.ql-editor').fill(Array.from({ length: 65 }, (_, i) => `検証の行${i + 1}：編集位置を確認します。`).join('\n'));
    await page.locator('#note-title').fill('自動保存で残す議事録');
    await saved();
    await page.reload();
    await page.waitForFunction(() => document.querySelector('.ql-editor')?.textContent.includes('検証の行65'));
    assert.equal(await page.locator('#note-title').inputValue(), '自動保存で残す議事録');
    await page.locator('.ql-editor p').nth(35).dblclick();
    const before = await page.evaluate(() => window.scrollY);
    assert(before > 400);
    await page.locator('.ql-header .ql-picker-label').click();
    await page.locator('.ql-header .ql-picker-item[data-value="2"]').click();
    await page.waitForFunction(y => Math.abs(scrollY - y) < 10, before);
    assert.match(await page.locator('.ql-editor h2').innerText(), /検証の行36/);
    await saved();
    console.log('PASS: title and body autosave survive reload; heading changes retain editing position');

    let fail = true;
    await page.route('**/meeting-notes/api/*/save', route => fail ? route.abort('failed') : route.continue());
    await page.locator('.ql-editor').click();
    await page.keyboard.press('Control+End');
    await page.keyboard.insertText('保存失敗後も残す');
    await page.waitForFunction(() => document.getElementById('save-status').textContent.includes('保存失敗'));
    fail = false;
    await saved();
    await page.unroute('**/meeting-notes/api/*/save');
    await page.reload();
    await page.waitForFunction(() => document.querySelector('.ql-editor')?.textContent.includes('保存失敗後も残す'));
    console.log('PASS: failed autosave remains unsaved, retries, and persists after recovery');

    const second = await context.newPage();
    await second.goto(noteUrl);
    await second.waitForFunction(() => document.querySelector('.ql-editor')?.getAttribute('contenteditable') === 'true');
    for (const [editor, text] of [[page, ' 共同編集A'], [second, ' 共同編集B']]) {
      await editor.locator('.ql-editor').click(); await editor.keyboard.press('Control+End'); await editor.keyboard.insertText(text);
    }
    await page.waitForFunction(() => document.querySelector('.ql-editor').textContent.includes('共同編集B') && document.getElementById('save-status').textContent.startsWith('保存済み '));
    await second.waitForFunction(() => document.getElementById('save-status').textContent.startsWith('保存済み '));
    await second.close();
    await page.reload();
    await page.waitForFunction(() => ['共同編集A', '共同編集B'].every(t => document.querySelector('.ql-editor')?.textContent.includes(t)));
    console.log('PASS: edits from two editors both survive reload');

    const day = '2026-09-16';
    const contactUrl = `${base}/parent-portal/children/${ids.child_id}/contact?date=${day}`;
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(contactUrl);
    const picker = page.locator('[data-temperature-picker="temperature"]');
    await picker.locator('[data-temperature-whole="37"]').click();
    assert.equal(await page.locator('#temperature').inputValue(), '37.');
    await picker.locator('[data-temperature-fraction="5"]').click();
    await page.getByRole('button', { name: '保存する', exact: true }).click();
    assert.equal(await page.locator('#temperature-error').isVisible(), true);
    await picker.locator('[data-temperature-fraction="4"]').click();
    await page.locator('[data-quick-choices="mood"] [data-choice="良好"]').click();
    await page.locator('[data-quick-choices="breakfast_status"] [data-choice="少なめ"]').click();
    assert.equal(await page.locator('#mood').inputValue(), '良好');
    assert.equal(await page.locator('#breakfast_status').inputValue(), '少なめ');
    if (process.env.TEST_SCREENSHOT_DIR) await page.screenshot({ path: path.join(process.env.TEST_SCREENSHOT_DIR, 'contact-tap-input.png') });
    await page.getByRole('button', { name: '保存する', exact: true }).click();
    await page.waitForURL('**/parent-portal/?date=2026-09-16&notice=saved');
    await page.goto(contactUrl);
    assert.equal(await page.locator('#temperature').inputValue(), '37.4');
    assert.equal(await picker.locator('[data-temperature-fraction="4"]').getAttribute('aria-pressed'), 'true');
    await page.locator('input[name="attendance_mode"][value="absent"]').check();
    await page.locator('input[name="absence_reason"][value="absent_sick"]').check();
    const sickPicker = page.locator('[data-temperature-picker="absence_temperature"]');
    await sickPicker.locator('[data-temperature-whole="38"]').click();
    await sickPicker.locator('[data-temperature-fraction="2"]').click();
    await page.locator('[name="absence_symptoms"]').fill('発熱');
    await page.getByRole('button', { name: '保存する', exact: true }).click();
    await page.waitForURL('**/parent-portal/?date=2026-09-16&notice=saved');
    console.log('PASS: touch choices retain values; 37.5 present is blocked and 38.2 sick absence is accepted');

    await context.request.post(`${base}/daily-contacts/${ids.child_id}/reply`, { form: { date: day, action: 'publish', reply_message: '園からの返信を確認' } });
    await page.goto(`${base}/parent-portal/?date=2026-09-17`);
    await page.getByRole('link', { name: /返信あり：/ }).click();
    await page.waitForURL('**#daily-contact-reply');
    assert.match(await page.locator('#daily-contact-reply').innerText(), /園からの返信を確認/);
    console.log('PASS: a previous date reply is visible from home and opens at the reply');

    const oralDay = '2026-09-18';
    await context.request.post(`${base}/attendance-checks/${ids.child_id}/verification`, { form: { date: oralDay, status: 'private_absent' } });
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${base}/attendance-checks/?date=${oralDay}`);
    const row = page.locator(`#attendance-check-row-${ids.child_id}`);
    assert.match(await row.innerText(), /アラーム/);
    await row.getByRole('button', { name: '詳細表示', exact: true }).click();
    const receipt = row.locator('form[action$="/contact-confirmation"]').first();
    await receipt.locator('[name="status"]').selectOption('private_absent');
    await receipt.locator('[name="note"]').fill('母から電話で連絡');
    await receipt.getByRole('button', { name: '連絡受付を記録' }).click();
    await page.waitForURL('**notice=contact_received');
    assert.match(await row.innerText(), /電話連絡受付/);
    assert.equal(await row.locator('span').filter({ hasText: /^アラーム$/ }).count(), 0);
    console.log('PASS: recording a phone contact clears the missing-contact alarm and shows the receipt');

    await page.goto(`${base}/guardian/terminal`);
    await page.locator('[name="kiosk_token"]').fill('synthetic-browser-token');
    await page.locator('form').getByRole('button').click();
    await page.waitForURL('**/guardian/terminal');
    const number = await page.locator('#terminal-registration-number').innerText();
    assert.match(number, /^[A-F0-9]{8}(?:-[A-F0-9]{8}){3}$/);
    await page.waitForFunction(() => document.getElementById('terminal-label')?.textContent);
    await page.goto(`${base}/settings/guardian-terminals`);
    assert.match(await page.locator('main').innerText(), new RegExp(number));
    assert.deepEqual(errors, []);
    console.log('PASS: registered kiosk and management screen show the same registration number');
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => { console.error(error); console.error(output); process.exitCode = 1; });
