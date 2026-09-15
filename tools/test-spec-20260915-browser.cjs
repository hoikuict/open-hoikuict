const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const port = Number(process.env.TEST_PORT || 18771);
const base = `http://127.0.0.1:${port}`;
const output = process.env.TEST_SCREENSHOT_DIR;
const server = spawn(process.env.TEST_PYTHON || 'python', ['-m', 'uvicorn', 'tools.spec_20260915_browser_fixture:app', '--host', '127.0.0.1', '--port', String(port)], {
  cwd: path.resolve(__dirname, '..'), windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  env: { ...process.env, HOIKUICT_DATABASE_URL: 'sqlite://', HOIKUICT_ENV: 'development', HOIKUICT_COOKIE_SECURE: '0' },
});
let log = '';
server.stdout.on('data', d => { log += d; });
server.stderr.on('data', d => { log += d; });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
(async () => {
  let browser;
  try {
    let ready = false;
    for (let i = 0; i < 100; i++) {
      try { ready = (await fetch(`${base}/openapi.json`)).ok; } catch (_) {}
      if (ready) break;
      if (server.exitCode !== null) throw new Error(log);
      await delay(100);
    }
    assert(ready, log);
    browser = await chromium.launch({ channel: 'msedge', headless: true });
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`${base}/__fixture_login`);
    await page.goto(`${base}/calendar/import`);
    await page.locator('[name="start"]').fill('2026-09-01');
    await page.locator('[name="end"]').fill('2026-09-30');
    await page.locator('[name="file"]').setInputFiles({ name: 'sample.ics', mimeType: 'text/calendar', buffer: Buffer.from('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:browser-import\r\nDTSTART;TZID=Asia/Tokyo:20260915T090000\r\nDTEND;TZID=Asia/Tokyo:20260915T100000\r\nSUMMARY:取込確認の会議\r\nRRULE:FREQ=WEEKLY;COUNT=2\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n') });
    await page.getByRole('button', { name: '取込内容を確認', exact: true }).click();
    await page.getByRole('button', { name: 'この2件を取り込む' }).waitFor();
    if (output) { fs.mkdirSync(output, { recursive: true }); await page.screenshot({ path: path.join(output, 'calendar-import.png'), fullPage: true }); }
    await page.getByRole('button', { name: 'この2件を取り込む' }).click();
    await page.waitForURL('**/calendar');
    assert((await page.locator('main').innerText()).includes('取込確認の会議'));
    console.log('PASS: ICS upload, recurrence preview and commit through browser');
    await page.goto(`${base}/meeting-notes/1`);
    await page.locator('.ql-editor[contenteditable="true"]').waitFor({ timeout: 60000 });
    await page.locator('#note-title').fill('9月15日 職員会議');
    await page.locator('.ql-editor').fill('会議の議題\n運動会の準備について確認しました。\n次回までに各クラスの計画をまとめます。');
    for (const name of ['Wordで出力', 'Markdownで出力']) {
      const downloadPromise = page.waitForEvent('download');
      await page.getByRole('button', { name, exact: true }).click();
      const download = await downloadPromise;
      assert(download.suggestedFilename().endsWith(name.startsWith('Word') ? '.docx' : '.md'));
      if (output) await download.saveAs(path.join(output, download.suggestedFilename()));
    }
    if (output) {
      await page.screenshot({ path: path.join(output, 'meeting-export.png'), fullPage: true });
      await page.emulateMedia({ media: 'print' });
      await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')));
      assert.equal(await page.locator('#markings').isVisible(), false);
      assert.equal(await page.locator('#meeting-print-title').isVisible(), true);
      await page.pdf({ path: path.join(output, 'meeting-print.pdf'), preferCSSPageSize: true });
      await page.emulateMedia({ media: 'screen' });
      await page.setViewportSize({ width: 390, height: 844 });
      const closeSidebar = page.getByRole('button', { name: '閉じる', exact: true });
      if (await closeSidebar.isVisible()) await closeSidebar.click();
      await page.waitForFunction(() => document.getElementById('staff-sidebar').getBoundingClientRect().right <= 0);
      await page.locator('#note-title').click();
      await page.screenshot({ path: path.join(output, 'meeting-export-mobile.png'), fullPage: true });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    }
    console.log('PASS: visible note exports to DOCX/Markdown and print layout hides editing controls');
    assert.deepEqual(errors, []);
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
