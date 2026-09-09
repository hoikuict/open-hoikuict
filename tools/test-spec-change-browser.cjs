// Run with TEST_PYTHON and PLAYWRIGHT_MODULE when using a bundled test runtime.
const assert = require('node:assert/strict');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const port = Number(process.env.TEST_PORT || 8767);
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
    const page = await browser.newPage({ viewport: { width: 1296, height: 970 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('requestfailed', request => console.error('Request failed:', request.url(), request.failure()?.errorText));
    await page.goto(`${base}/__fixture_login`);
    await page.waitForFunction(() => getComputedStyle(document.querySelector('main')).paddingLeft !== '0px');
    for (const width of [375, 768, 1024, 1296, 1536, 1920]) {
      await page.setViewportSize({ width, height: 970 });
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const size = await page.locator('[id^="attendance-check-row-"]').first().evaluate(row => {
        const name = row.querySelector('h2');
        const rect = name.getBoundingClientRect();
        return { name: name.textContent, width: rect.width, height: rect.height,
          columnWidth: name.parentElement.getBoundingClientRect().width,
          overflow: document.documentElement.scrollWidth - window.innerWidth,
          clipped: name.scrollWidth > name.clientWidth,
          actionsInside: [...row.querySelectorAll('form button')].every(button => button.getBoundingClientRect().right <= row.getBoundingClientRect().right) };
      });
      assert(size.columnWidth >= 140 && size.width > 100 && size.height > 0 && !size.clipped, `name at ${width}: ${JSON.stringify(size)}`);
      assert(size.overflow <= 1 && size.actionsInside, `overflow at ${width}: ${JSON.stringify(size)}`);
      if (width === 1296 && process.env.TEST_SCREENSHOT_DIR) {
        await page.screenshot({ path: path.join(process.env.TEST_SCREENSHOT_DIR, 'attendance-checks-tablet.png') });
      }
    }
    console.log('PASS: readable names and contained actions at six phone/tablet/desktop widths');

    await page.setViewportSize({ width: 1296, height: 970 });
    await page.goto(`${base}/attendance/?start_date=2026-09-09&end_date=2026-09-09&sort_by=classroom&sort_order=asc`);
    const punch = page.locator('[data-preserve-attendance-scroll]').nth(35);
    await punch.scrollIntoViewIfNeeded();
    await page.locator('#attendance-table-scroll').evaluate(table => { table.scrollLeft = table.scrollWidth; });
    const before = await page.evaluate(() => ({ y: scrollY, x: document.getElementById('attendance-table-scroll').scrollLeft }));
    assert(before.y > 500 && before.x > 0);
    await Promise.all([page.waitForNavigation({ waitUntil: 'load' }), punch.getByRole('button').click()]);
    await page.waitForFunction(y => Math.abs(scrollY - y) < 3, before.y);
    assert(Math.abs(await page.locator('#attendance-table-scroll').evaluate(table => table.scrollLeft) - before.x) < 3);
    assert.match(await page.locator('[data-preserve-attendance-scroll]').nth(35).innerText(), /降園打刻/);
    console.log('PASS: punch preserves vertical/horizontal position and updates attendance');

    await page.goto(`${base}/meeting-notes/1`);
    await page.locator('.ql-editor[contenteditable="true"]').waitFor();
    await page.locator('.ql-editor').fill('保存前の議事録本文を保持する。');
    await page.locator('#highlight-excerpt').fill('保存前の議事録本文');
    await page.getByRole('button', { name: 'マーキングを保存', exact: true }).click();
    await page.waitForURL('**/meeting-notes/1#markings');
    await page.waitForFunction(() => document.querySelector('.ql-editor')?.textContent.includes('本文を保持する'));
    assert.equal(await page.locator('#markings blockquote').count(), 1);
    console.log('PASS: marking saves an unsaved note and retains it after navigation');

    // Saving failure must leave both the editor and excerpt intact, without submitting a marking.
    await page.locator('.ql-editor').fill('保存障害があっても消えてはいけない本文。');
    await page.locator('#highlight-excerpt').fill('失敗時の抜き書き');
    await page.route('**/meeting-notes/api/1/save', route => route.fulfill({ status: 500, body: 'test failure' }));
    await page.getByRole('button', { name: 'マーキングを保存', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#sync-status').textContent.includes('本文の保存に失敗'));
    assert.match(await page.locator('.ql-editor').innerText(), /消えてはいけない/);
    assert.equal(await page.locator('.ql-editor').getAttribute('contenteditable'), 'true');
    assert.equal(await page.locator('#highlight-excerpt').inputValue(), '失敗時の抜き書き');
    assert.equal(await page.locator('#markings blockquote').count(), 1);
    await page.unroute('**/meeting-notes/api/1/save');
    await page.getByRole('button', { name: 'マーキングを保存', exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll('#markings blockquote').length === 2);
    await page.waitForFunction(() => document.querySelector('.ql-editor')?.textContent.includes('消えてはいけない'));
    console.log('PASS: failed save prevents marking submission; retry preserves the draft');

    let savesAfterLoadFailure = 0;
    await page.route('**/meeting-notes/api/1/content', route => route.fulfill({ status: 500, body: 'test load failure' }));
    await page.route('**/meeting-notes/api/1/save', route => { savesAfterLoadFailure++; return route.continue(); });
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#sync-status').textContent === '読込失敗');
    await page.locator('#highlight-excerpt').fill('読込失敗時は送信しない');
    await page.getByRole('button', { name: 'マーキングを保存', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#sync-status').textContent.includes('本文の保存に失敗'));
    assert.equal(savesAfterLoadFailure, 0);
    assert.equal(await page.locator('#markings blockquote').count(), 2);
    console.log('PASS: failed initial load cannot overwrite an existing note');
    assert.deepEqual(errors, [], 'unexpected browser errors');
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
