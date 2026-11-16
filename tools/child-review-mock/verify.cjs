// Run Chromium against only the three local mock assets.
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: 'ja-JP' });
    const errors = [];
    page.on('pageerror', err => errors.push(String(err)));
    const root = 'http://mock.test/';
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      const asset = url.pathname.slice(1) || 'index.html';
      assert.equal(url.origin + '/', root);
      assert.equal(route.request().method(), 'GET');
      assert(['index.html', 'mock.css', 'mock.js'].includes(asset));
      await route.fulfill({ path: path.join(__dirname, asset) });
    });
    const button = name => page.getByRole('button', { name, exact: true });
    const click = name => button(name).click();
    const visible = async id => assert(await page.locator(id).isVisible(), id);
    const text = id => page.locator(id).innerText();
    const example = async value => {
      if (!await page.locator('#example').isVisible()) await page.locator('#settings summary').click();
      await page.locator('#example').selectOption(value);
    };
    await page.goto(root);
    const originalAndAddition = await page.locator('#overview').inputValue();
    await click('詳細・承認へ');
    await visible('#unsaved');
    await click('入力を続ける');
    assert.equal(await page.locator('#overview').inputValue(), originalAndAddition);
    await click('詳細・承認へ');
    await click('保存せず切り替える');
    assert(!(await text('#report-body')).includes('にっこり'));
    await click('修正');
    assert(!(await page.locator('#overview').inputValue()).includes('にっこり'));

    await click('追記して詳細へ進む');
    await page.locator('#settings summary').click();
    await page.locator('#fail').check();
    await page.locator('#evidence').uncheck();
    await click('詳細・承認へ');
    await click('保存して切り替える');
    await visible('#editor');
    await visible('#save-error');
    assert.equal(await page.locator('#overview').inputValue(), originalAndAddition);
    assert(!await page.locator('#evidence').isChecked());
    await click('保存して切り替える');
    await visible('#detail');
    assert((await text('#report-body')).includes('にっこり'));
    assert.equal(await page.locator('#report-body small').count(), 0);
    await click('修正');
    assert.equal(await page.locator('#overview').inputValue(), originalAndAddition);
    await page.locator('#overview').fill('');
    await click('詳細・承認へ');
    await click('保存して切り替える');
    await visible('#save-error');
    await visible('#editor');
    await example('new');
    assert(!await button('詳細・承認へ').isVisible());
    await page.locator('#overview').fill('新規の入力例。');
    await click('下書きを保存');
    await visible('#saved-notice');
    await click('詳細・承認へ');
    assert((await text('#report-body')).includes('新規の入力例。'));
    await click('管理者がいないとき');
    for (const [value, label] of [['filled', '下書き'], ['returned', '差戻し']]) {
      await example(value);
      await page.locator('#admins').selectOption('0');
      const before = await text('#report-body');
      await click('レビュー依頼');
      await visible('#review-error');
      assert.equal(await text('#detail-status'), label);
      assert.equal(await text('#report-body'), before);
      assert((await text('#notice-count')).includes('0件'));
      await page.locator('#admins').selectOption('1');
      await click('レビュー依頼');
      assert.equal(await text('#detail-status'), 'レビュー待ち');
      assert.equal(await text('#report-body'), before);
      assert((await text('#notice-count')).includes('1件'));
      assert(!await button('レビュー依頼').isVisible());
      await click('レビューを取り下げる');
      assert.equal(await text('#detail-status'), '下書き');
      assert((await text('#notice-count')).includes('0件'));
    }
    await click('スマホで記録を探す');
    const layout = () => page.evaluate(() => {
      const log = document.querySelector('.logs').getBoundingClientRect();
      const fields = document.querySelector('.fields').getBoundingClientRect();
      return { below: log.top >= fields.bottom, right: log.left >= fields.right,
        overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth };
    });
    assert((await layout()).below);
    await page.locator('#settings summary').click();
    await page.locator('#phone').uncheck();
    assert((await layout()).right);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('#jump-logs').click();
    assert((await layout()).below && !(await layout()).overflow);
    assert(await page.locator('#logs-title').evaluate(el => el.getBoundingClientRect().top < innerHeight && el.getBoundingClientRect().bottom > 0));
    assert.deepEqual(errors, []);
    console.log('Verified three unsaved choices, validation, retry, evidence, draft/returned recipient checks, withdrawal and responsive record placement. Local GETs only.');
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
