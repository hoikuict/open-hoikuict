// Synthetic local verification, including CSRF-protected submissions.
const assert = require('node:assert/strict');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const port = Number(process.env.TEST_PORT || 8769);
const base = `http://127.0.0.1:${port}`;
const server = spawn(process.env.TEST_PYTHON || 'venv/Scripts/python.exe', ['-m', 'uvicorn', 'tools.spec_20260911_browser_fixture:app', '--host', '127.0.0.1', '--port', String(port)], {
  cwd: path.resolve(__dirname, '..'), windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  env: { ...process.env, HOIKUICT_DATABASE_URL: 'sqlite://', HOIKUICT_ENV: 'development', HOIKUICT_COOKIE_SECURE: '0', HOIKUICT_CSRF_ENFORCE: '1' },
});
let serverOutput = '';
server.stdout.on('data', data => { serverOutput += data; });
server.stderr.on('data', data => { serverOutput += data; });
(async () => {
  let browser;
  try {
    let ready = false;
    for (let i = 0; i < 100; i++) {
      try { ready = (await fetch(`${base}/openapi.json`)).ok; } catch (_) {}
      if (ready) break;
      if (server.exitCode !== null) throw new Error(serverOutput);
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(ready, serverOutput);
    browser = await chromium.launch({ channel: 'msedge', headless: true });
    const page = await browser.newPage({ viewport: { width: 1280, height: 960 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('requestfailed', request => console.error('Request failed:', request.url(), request.failure()?.errorText));
    await page.goto(`${base}/__fixture_login`);
    await page.goto(`${base}/guardian/terminal`);
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
    const shot = async name => { if (process.env.TEST_SCREENSHOT_DIR) await page.screenshot({ path: path.join(process.env.TEST_SCREENSHOT_DIR, name) }); };
    for (const width of [390, 768, 1280]) {
      await page.setViewportSize({ width, height: 960 });
      await page.goto(`${base}/guardian/?class_id=1&child_id=1&date=${today}`);
      await page.locator('[data-pickup-hour="16"]').waitFor();
      await page.locator('[data-pickup-hour="16"]').scrollIntoViewIfNeeded();
      await shot(`kiosk-input-${width}.png`);
      console.log('Kiosk style:', await page.locator('[data-pickup-hour="16"]').evaluate(el => ({ font: getComputedStyle(el).fontSize, height: el.offsetHeight })));
      await page.waitForFunction(() => getComputedStyle(document.querySelector('[data-pickup-hour="16"]')).fontSize === '24px');
      const sizes = await page.locator('[data-pickup-hour="16"]').evaluate(button => ({ width: button.offsetWidth, height: button.offsetHeight, overflow: document.documentElement.scrollWidth - innerWidth }));
      assert(sizes.height >= 80 && sizes.width >= 70 && sizes.overflow <= 1, JSON.stringify(sizes));
      await page.locator('[data-pickup-hour="17"]').click();
      await page.locator('[data-pickup-minute="30"]').click();
      await page.locator('[data-pickup-person]').first().click();
      await page.getByRole('button', { name: '確認へ', exact: true }).click();
      await page.waitForURL('**/guardian/child/1/pickup');
      assert.equal(await page.locator('section > div.text-2xl').evaluate(el => getComputedStyle(el).fontSize), '24px');
      await shot(`kiosk-confirm-${width}.png`);
    }
    console.log('PASS: kiosk input and 24px confirmation at 390/768/1280px');
    await page.goto(`${base}/staff-rooms/threads/1`);
    assert.equal(await page.locator('#thread-panel a[href="https://example.test/form"]').count(), 1);
    assert.equal(await page.locator('html').count(), 1);
    await shot('thread-page.png');
    await page.goto(`${base}/families/?q=園児01`);
    assert.match(await page.locator('main').innerText(), /表示確認家/);
    await page.goto(`${base}/parent-accounts/new?family_id=1`);
    await page.locator('#select-family-children').click();
    assert.equal(await page.locator('input[name="child_ids"]:checked').count(), 2);
    assert.equal(await page.locator('[data-family-child]:visible').count(), 2);
    await page.goto(`${base}/document-reviews/`);
    await page.getByText('新しい確認依頼', { exact: true }).click();
    await page.locator('input[name="title"]').fill('ブラウザー検証の文書');
    await page.locator('textarea[name="body"]').fill('確認用の本文です。');
    await page.getByRole('button', { name: '管理者に確認を依頼する' }).click();
    await page.waitForURL('**/document-reviews/1');
    assert.match(await page.locator('main').innerText(), /確認用の本文/);
    await shot('document-review.png');
    await page.goto(`${base}/attendance/1/correction?date=${today}`);
    await page.locator('textarea[name="reason"]').fill('ブラウザー検証の誤打刻');
    await page.getByRole('button', { name: '確認した打刻を取り消す' }).click();
    await page.waitForURL('**/attendance/**');
    await page.goto(`${base}/attendance/1/correction?date=${today}`);
    assert.match(await page.locator('main').innerText(), /未打刻/);
    assert.match(await page.locator('article').innerText(), /ブラウザー検証の誤打刻/);
    await page.goto(`${base}/settings/guardian-terminals`);
    await page.locator('input[name="label"]').fill('玄関の共用端末');
    await page.getByRole('button', { name: '保存', exact: true }).click();
    await page.waitForLoadState('networkidle');
    assert.equal(await page.locator('input[name="label"]').inputValue(), '玄関の共用端末');
    assert.deepEqual(errors, []);
    console.log('PASS: thread link, family search/sibling selection, document submission, punch cancellation and monitor settings');
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
