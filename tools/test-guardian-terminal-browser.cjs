const assert = require('node:assert/strict');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const port = Number(process.env.TEST_PORT || 8768);
const base = `http://127.0.0.1:${port}`;
const python = process.env.TEST_PYTHON || (process.platform === 'win32' ? 'venv/Scripts/python.exe' : 'python');
const server = spawn(python, ['-m', 'uvicorn', 'tools.spec_change_browser_fixture:app', '--host', '127.0.0.1', '--port', String(port)], {
  cwd: path.resolve(__dirname, '..'), windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  env: { ...process.env, HOIKUICT_DATABASE_URL: 'sqlite://', HOIKUICT_ENV: 'development', HOIKUICT_COOKIE_SECURE: '0' },
});
let serverOutput = '';
server.stdout.on('data', data => { serverOutput += data; });
server.stderr.on('data', data => { serverOutput += data; });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  let browser;
  try {
    let ready = false;
    for (let attempt = 0; attempt < 100; attempt++) {
      try { ready = (await fetch(`${base}/openapi.json`)).ok; } catch (_) {}
      if (ready) break;
      if (server.exitCode !== null) throw new Error(serverOutput);
      await delay(100);
    }
    assert(ready, serverOutput);
    browser = await chromium.launch({ channel: process.env.TEST_BROWSER_CHANNEL || 'msedge', headless: true });
    const context = await browser.newContext({ viewport: { width: 1366, height: 900 }, hasTouch: true });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.clock.install();
    await page.goto(`${base}/guardian/terminal`);
    await page.waitForFunction(() => getComputedStyle(document.querySelector('header')).backgroundColor === 'rgb(67, 56, 202)');
    assert.equal(await page.locator('#staff-sidebar').count(), 0);
    const manifest = await (await context.request.get(`${base}/guardian/manifest.webmanifest`)).json();
    assert.equal(manifest.start_url, '/guardian/terminal');
    assert.equal(manifest.display, 'standalone');
    const chooseChild = async index => {
      await page.getByRole('link', { name: '検証クラス', exact: true }).click();
      await page.getByRole('link', { name: `表示確認 園児${String(index).padStart(2, '0')}`, exact: true }).click();
      await page.locator('form input[name="csrf_token"]').first().waitFor({ state: 'attached' });
    };
    await chooseChild(0);
    assert.equal(await page.locator('input[type="date"]').count(), 0);
    assert.equal(await page.getByRole('link', { name: '表示確認 園児01', exact: true }).count(), 0);
    await page.getByRole('button', { name: '登園する', exact: true }).click();
    await page.locator('[data-pickup-hour="17"]').click();
    await page.locator('[data-pickup-minute="15"]').click();
    await page.locator('[data-pickup-person="母"]').click();
    if (process.env.TEST_SCREENSHOT_DIR) await page.screenshot({ path: path.join(process.env.TEST_SCREENSHOT_DIR, 'guardian-terminal.png') });
    await page.getByRole('button', { name: '確認へ', exact: true }).click();
    assert.match(await page.locator('main').innerText(), /17:15/);
    await page.getByRole('button', { name: '決定', exact: true }).click();
    await page.clock.fastForward(1100);
    await page.waitForURL('**/guardian/terminal');
    await chooseChild(0);
    await page.getByRole('button', { name: '降園する', exact: true }).click();
    await page.getByRole('button', { name: '決定', exact: true }).click();
    await page.clock.fastForward(1100);
    await page.waitForURL('**/guardian/terminal');
    console.log('PASS: touch flow records arrival, pickup plan and departure; each completion clears the selection');

    await chooseChild(1);
    await page.clock.fastForward(76000);
    assert.equal(await page.locator('#terminal-idle-warning').isVisible(), true);
    await page.getByRole('button', { name: '操作を続ける', exact: true }).click();
    assert.equal(await page.locator('#terminal-idle-warning').isVisible(), false);
    await page.clock.fastForward(91000);
    await page.waitForURL('**/guardian/terminal');
    assert.equal(await page.locator('#guardian-terminal').getAttribute('data-active'), '0');
    console.log('PASS: idle warning, continue and 90-second reset clear the previous child');

    await chooseChild(1);
    let offlinePosts = 0;
    page.on('request', request => { if (!page.isClosed() && request.method() === 'POST') offlinePosts++; });
    await context.setOffline(true);
    await page.waitForFunction(() => !document.getElementById('terminal-warning').hidden);
    assert.equal(await page.getByRole('button', { name: '登園する', exact: true }).isDisabled(), true);
    await page.clock.fastForward(91000);
    assert.equal(await page.locator('main').isVisible(), false);
    await context.setOffline(false);
    await page.waitForURL('**/guardian/terminal');
    assert.equal(offlinePosts, 0);
    console.log('PASS: offline state disables writes; reconnection resets without replaying any punch');

    await chooseChild(1);
    let changedDate = false;
    await page.route('**/guardian/terminal/status', route => {
      if (changedDate) return route.continue();
      changedDate = true;
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ kiosk: true, today: '2099-01-01' }) });
    });
    await page.clock.fastForward(31000);
    await page.waitForURL('**/guardian/terminal');
    assert(changedDate);
    console.log('PASS: server date change discards the old selection');
    assert.deepEqual(errors, [], 'unexpected browser errors');
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
