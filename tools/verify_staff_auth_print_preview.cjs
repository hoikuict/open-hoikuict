const { chromium } = require('C:/Users/katet/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const folder = path.resolve('tools/staff-auth-print-preview');
const output = path.resolve('output/pdf');

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Users/katet/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const errors = [], external = [], writes = [], checks = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', request => {
    if (!request.url().startsWith('http://127.0.0.1:8898/')) external.push(request.url());
    if (!['GET', 'HEAD'].includes(request.method())) writes.push(request.url());
  });
  page.on('dialog', dialog => dialog.dismiss());
  const select = (name, value) => page.locator('#preview-' + name).selectOption(value);
  try {
    await page.goto('http://127.0.0.1:8898/');
    await page.locator('#printed-code').waitFor();
    await page.waitForFunction(() => getComputedStyle(document.querySelector('.bg-slate-50')).backgroundColor === 'rgb(248, 250, 252)');
    await page.evaluate(() => { window.printCalls = 0; window.print = () => { window.printCalls++; }; });
    for (const action of ['activate', 'reset']) {
      await select('action', action);
      assert.equal(await page.locator('#printed-code').innerText(), action === 'activate' ? 'H7K3MP' : 'R9T4NW');
      assert.ok(await page.locator('.qr-wrap svg').isVisible());
      const count = await page.evaluate(() => window.staffPrintPreview.issuedCount());
      await page.locator('#print-handout').click();
      assert.equal(await page.evaluate(() => window.staffPrintPreview.issuedCount()), count);
      await page.locator('#back-admin').click();
      assert.ok(await page.locator('#handout').isVisible(), 'cancel leaving preserves handout');
      await page.screenshot({ path: path.join(folder, `verified-${action}-desktop.png`), fullPage: true });
      await page.pdf({ path: path.join(output, `staff-${action}-handout-preview.pdf`), preferCSSPageSize: true, printBackground: false, displayHeaderFooter: false });
      checks.push(`${action}: A4 PDF generated, print and navigation cancel preserve code`);
      for (const state of ['expired', 'urlmissing']) {
        await select('state', state);
        assert.ok(await page.locator('#print-handout').isDisabled());
        assert.ok(await page.locator('[role=alert]').isVisible());
      }
      await select('state', 'filled');
      await select('view', 'admin');
      assert.deepEqual(await page.locator('#mock-view input').evaluateAll(nodes => nodes.map(n => n.name)), action === 'activate' ? ['login_id', 'reason'] : ['reason']);
      for (const state of ['empty', 'partial', 'filled', 'error']) {
        await select('state', state);
        if (state === 'empty' || state === 'partial') assert.equal(await page.locator('[name=reason]').inputValue(), '');
        if (state === 'error') {
          await page.locator('[name=reason]').fill('保持する発行理由');
          await page.locator('#mock-view form button').click();
          assert.equal(await page.locator('[name=reason]').inputValue(), '保持する発行理由');
        }
      }
      await select('state', 'filled');
      await page.locator('#mock-view form button').click();
      assert.ok(await page.locator('#handout').isVisible());
      await page.locator('#try-recipient').click();
      assert.deepEqual(await page.locator('#mock-view input').evaluateAll(nodes => nodes.map(n => n.name)), action === 'activate' ? ['activation_code'] : ['reset_code', 'password', 'password_confirmation']);
      await page.locator(`[name=${action === 'activate' ? 'activation_code' : 'reset_code'}]`).fill(action === 'activate' ? 'H7K3MP' : 'R9T4NW');
      if (action === 'activate') {
        await page.locator('#mock-view form button').click();
        assert.deepEqual(await page.locator('#mock-view input').evaluateAll(nodes => nodes.map(n => n.name)), ['login_id', 'password', 'password_confirmation']);
      }
      await page.locator('[name=password]').fill('Preview2026!');
      await page.locator('[name=password_confirmation]').fill('Different2026!');
      await page.locator('#mock-view form button').click();
      assert.match(await page.locator('[role=alert]').innerText(), /一致しません/);
      await page.locator('[name=password_confirmation]').fill('Preview2026!');
      await page.locator('#mock-view form button').click();
      assert.match(await page.locator('#mock-view').innerText(), /設定が完了/);
      await page.locator('#again').click();
      checks.push(`${action}: original input fields, blank/partial/error states, issue and recipient completion`);
    }
    await select('action', 'activate');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.getElementById('staff-sidebar').getBoundingClientRect().right <= 1);
    await page.screenshot({ path: path.join(folder, 'verified-mobile.png'), fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'no mobile horizontal overflow');
    await select('view', 'admin');
    await page.screenshot({ path: path.join(folder, 'verified-admin-mobile.png'), fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await page.locator('[data-sidebar-open]').click();
    await page.locator('[data-sidebar-close]').click();
    await page.waitForFunction(() => document.getElementById('staff-sidebar').getBoundingClientRect().right <= 1);
    assert.deepEqual(errors, []); assert.deepEqual(external, []); assert.deepEqual(writes, []);
    checks.push('390 px mobile without overflow; no JS exceptions, external requests, or write requests');
    fs.writeFileSync(path.join(folder, 'verification.json'), JSON.stringify({ mockOnly: true, checks, errors, external, writes, liveServerChecked: false }, null, 2));
    console.log(JSON.stringify({ checks, errors, external, writes }, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
