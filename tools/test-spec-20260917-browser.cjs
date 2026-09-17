const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const port = Number(process.env.TEST_PORT || 8772);
const base = `http://127.0.0.1:${port}`;
const screenshots = process.env.TEST_SCREENSHOT_DIR || path.join(root, 'tmp_spec_review_20260917', 'screenshots');
fs.mkdirSync(screenshots, { recursive: true });
const python = process.env.TEST_PYTHON || (process.platform === 'win32' ? 'venv/Scripts/python.exe' : 'python');
const server = spawn(python, ['-m', 'uvicorn', 'tools.spec_20260917_browser_fixture:app', '--host', '127.0.0.1', '--port', String(port)], {
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
      try { const res = await fetch(`${base}/__fixture17`); if (res.ok) { ids = await res.json(); break; } } catch (_) {}
      if (server.exitCode !== null) throw new Error(output);
      await pause(100);
    }
    assert(ids, output);
    browser = await chromium.launch({ channel: process.env.TEST_BROWSER_CHANNEL || 'msedge', headless: true });
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, ignoreHTTPSErrors: true });
    await context.request.get(`${base}/__fixture_login`);
    await context.request.post(`${base}/parent-portal/login`, { form: { parent_account_id: String(ids.parent_id) } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`${base}/parent-portal/`);
    await page.waitForFunction(() => getComputedStyle(document.querySelector('nav')).backgroundColor === 'rgb(67, 56, 202)');
    const menu = page.locator('nav details');
    assert.equal(await menu.getAttribute('open'), null);
    await menu.locator('summary').click();
    assert(await menu.getByRole('link', { name: '登録情報', exact: true }).isVisible());
    assert.equal(await page.getByRole('link', { name: '通知設定', exact: true }).count(), 1);
    await page.screenshot({ path: path.join(screenshots, 'parent-menu.png') });
    await page.goto(`${base}/parent-portal/children/${ids.child_id}/contact?date=${ids.today}`);
    await page.locator('[name="bedtime"]').fill('21:00');
    await page.locator('[name="wakeup_time"]').fill('06:30');
    await page.locator('[name="breakfast_contents"]').fill('ごはん、卵、みそ汁');
    await page.locator('[name="stool_consistency"]').selectOption('normal');
    await page.locator('[name="stool_count"]').fill('1');
    await page.locator('[name="temperature"]').fill('36.5');
    await page.screenshot({ path: path.join(screenshots, 'parent-contact.png'), fullPage: true });
    await page.getByRole('button', { name: '保存する', exact: true }).click();
    await page.waitForURL('**/parent-portal/?**');
    await page.goto(`${base}/parent-portal/history`);
    assert.match(await page.locator('main').innerText(), /9時間30分/);
    console.log('PASS: compact parent menu and structured care fields persist, including overnight sleep');

    await page.goto(`${base}/parent-portal/children/${ids.child_id}/pickup?date=${ids.today}`);
    await page.locator('[name="planned_pickup_time"]').fill('17:30');
    await page.locator('[name="pickup_person"]').fill('母');
    await page.getByRole('button', { name: '予定を保存' }).click();
    await page.waitForURL('**/parent-portal/?**');
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${base}/guardian/terminal`);
    await page.locator('[name="kiosk_token"]').fill('synthetic-browser-token');
    await page.locator('form').getByRole('button').click();
    await page.waitForURL('**/guardian/terminal');
    await page.waitForFunction(() => /^\d{2}:\d{2}:\d{2}$/.test(document.getElementById('terminal-clock').textContent));
    assert(await page.evaluate(() => parseFloat(getComputedStyle(document.getElementById('terminal-clock')).fontSize) >= 40));
    const firstClock = await page.locator('#terminal-clock').innerText();
    await page.waitForFunction(value => document.getElementById('terminal-clock').textContent !== value, firstClock);
    assert(await page.evaluate(() => document.getElementById('terminal-registration-number').getBoundingClientRect().top >= document.querySelector('main').getBoundingClientRect().bottom));
    await page.screenshot({ path: path.join(screenshots, 'terminal-clock.png') });
    await page.goto(`${base}/guardian/?date=${ids.today}&child_id=${ids.child_id}`);
    assert(await page.getByRole('button', { name: '登園する', exact: true }).isVisible());
    assert.equal(await page.locator('[name="planned_pickup_time"]').inputValue(), '17:30');
    await page.locator('[data-pickup-hour="18"]').click();
    await page.locator('[data-pickup-minute="15"]').click();
    await page.locator('[data-pickup-person="父"]').click();
    await page.getByRole('button', { name: '確認へ', exact: true }).click();
    await page.getByRole('button', { name: '決定', exact: true }).click();
    await page.waitForURL('**/guardian/terminal');
    await page.goto(`${base}/parent-portal/children/${ids.child_id}/pickup?date=${ids.today}`);
    assert.equal(await page.locator('[name="planned_pickup_time"]').inputValue(), '18:15');
    assert.equal(await page.locator('[name="pickup_person"]').inputValue(), '父');
    console.log('PASS: live kiosk clock, footer registration, and shared pickup edits before arrival');

    await page.goto(`${base}/children/${ids.child_id}/health/check-records?edit=${ids.record_id}`);
    await page.locator('[name="height_cm"]').fill('96.2');
    await page.locator('[name="correction_reason"]').fill('入力値の確認');
    await page.getByRole('button', { name: '訂正を保存する' }).click();
    await page.waitForURL('**/*notice=corrected');
    assert.match(await page.locator('main').innerText(), /96.2/);
    await page.waitForFunction(() => Chart.getChart('height-chart')?.data.datasets[0].data.includes(96.2));
    await pause(1200);
    await page.getByText(/画面検証|入力値の確認/).last().click().catch(() => {});
    await page.screenshot({ path: path.join(screenshots, 'health-correction.png'), fullPage: true });
    await page.goto(`${base}/surveys/${ids.survey_id}/edit`);
    assert(await page.getByRole('heading', { name: '結果を閲覧できる職員' }).isVisible());
    await page.goto(`${base}/child-records/progress?group_by=age`);
    assert(await page.locator('[name="classroom_id"]').isVisible());
    assert.equal(await page.locator('[name="group_by"]').inputValue(), 'age');
    assert.deepEqual(errors, []);
    console.log('PASS: health correction, survey result controls, class/age filters; no JavaScript errors');
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => { console.error(error); console.error(output.slice(-3000)); process.exitCode = 1; });
