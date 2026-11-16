const { chromium } = require('C:/Users/katet/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const root = process.cwd(), output = path.join(root, '.local-dev/staff-handout-verification');
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Users/katet/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe' });
  const errors = [], unexpected = [], writes = [], checks = [];
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  // Fulfil every resource locally. No service or production server is contacted.
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (!['GET', 'HEAD'].includes(request.method())) writes.push(request.method() + ' ' + request.url());
    if (url.hostname === 'cdn.tailwindcss.com') return route.fulfill({ path: path.join(root, 'tools/staff-auth-print-preview/tailwind.js'), contentType: 'application/javascript' });
    if (url.hostname === 'unpkg.com') return route.fulfill({ body: '', contentType: 'application/javascript' });
    if (url.hostname === 'handout.invalid') {
      if (['/activate.html', '/reset.html', '/long.html'].includes(url.pathname)) return route.fulfill({ path: path.join(output, url.pathname.slice(1)), contentType: 'text/html' });
      if (['/static/css/staff-auth-handout.css', '/static/js/staff-auth-handout.js'].includes(url.pathname)) return route.fulfill({ path: path.join(root, url.pathname.slice(1)), contentType: url.pathname.endsWith('.css') ? 'text/css' : 'application/javascript' });
      if (url.pathname === '/staff/users') return route.fulfill({ body: '<h1>確認用の戻り先</h1>', contentType: 'text/html' });
    }
    unexpected.push(request.url());
    return route.abort();
  });
  try {
    for (const mode of ['activate', 'reset', 'long']) {
      const page = await context.newPage();
      await page.clock.install();
      page.on('pageerror', e => errors.push(e.message));
      page.on('dialog', d => d.dismiss());
      await page.goto('https://handout.invalid/' + mode + '.html');
      await page.locator('#credential-action-code').waitFor();
      await page.waitForFunction(() => document.getElementById('staff-handout-qr').complete && document.getElementById('staff-handout-qr').naturalWidth > 0);
      const code = await page.locator('#credential-action-code').innerText();
      await page.evaluate(() => { window.printCalls = 0; window.print = () => { window.printCalls++; }; });
      await page.locator('#print-staff-handout').click();
      assert.equal(await page.evaluate(() => window.printCalls), 1);
      assert.equal(await page.locator('#credential-action-code').innerText(), code);
      await page.locator('#staff-code-back').click();
      assert.ok(page.url().endsWith(mode + '.html'));
      assert.equal(await page.locator('#credential-action-code').innerText(), code);
      await page.pdf({ path: path.join(output, mode + '.pdf'), preferCSSPageSize: true, printBackground: false, displayHeaderFooter: false });
      await page.locator('#staff-action-page').screenshot({ path: path.join(output, mode + '-desktop.png') });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForFunction(() => document.getElementById('staff-sidebar').getBoundingClientRect().right <= 1);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), mode + ': mobile overflow');
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: path.join(output, mode + '-mobile.png'), fullPage: true });
      await page.evaluate(() => { Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => { throw Error('denied'); } } }); });
      await page.locator('#copy-action-code').click();
      assert.match(await page.locator('#staff-code-status').innerText(), /コピーできません/);
      await page.clock.fastForward(31 * 60 * 1000);
      assert.ok(await page.locator('#print-staff-handout').isDisabled());
      assert.ok(await page.locator('#staff-code-expired').isVisible());
      await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')));
      assert.equal(await page.evaluate(() => window.printCalls), 1);
      await page.evaluate(() => { window.dispatchEvent(new Event('pagehide')); window.dispatchEvent(new Event('pageshow')); });
      assert.equal(await page.locator('#credential-action-code').innerText(), '');
      assert.ok(await page.locator('#staff-handout').isHidden());
      assert.match(await page.locator('#staff-code-expired').innerText(), /再表示できません/);
      checks.push(mode + ': actual template, print/cancel, mobile, clipboard failure, expiry and history return');
      await page.close();
    }
    assert.deepEqual(errors, []); assert.deepEqual(unexpected, []); assert.deepEqual(writes, []);
    fs.writeFileSync(path.join(output, 'browser.json'), JSON.stringify({ checks, errors, unexpected, writes, allNetworkFulfilledLocally: true }, null, 2));
    console.log(JSON.stringify({ checks, errors, unexpected, writes }, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
