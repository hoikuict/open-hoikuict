const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawn,spawnSync} = require('node:child_process');
const {pathToFileURL} = require('node:url');
const {deflateRawSync} = require('node:zlib');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const port = Number(process.env.TEST_PORT || 18772), base = `http://127.0.0.1:${port}`;
const output = process.env.TEST_SCREENSHOT_DIR;
const server = spawn(process.env.TEST_PYTHON || 'python', ['-m','uvicorn','tools.migration_converter_browser_fixture:app','--host','127.0.0.1','--port',String(port)], {cwd:path.resolve(__dirname,'..'),windowsHide:true,stdio:['ignore','pipe','pipe'],env:{...process.env,HOIKUICT_DATABASE_URL:'sqlite://',HOIKUICT_ENV:'development',HOIKUICT_COOKIE_SECURE:'0',HOIKUICT_CSRF_ENFORCE:'1',HOIKUICT_PREVIEW_DIR:process.env.TEST_PREVIEW_DIR || path.resolve('storage/migration-test-previews')}});
let log='';server.stdout.on('data',d=>log+=d);server.stderr.on('data',d=>log+=d);
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function zip(files) {
  const locals=[],centrals=[];let offset=0;
  for(const [name,value] of Object.entries(files)){
    const filename=Buffer.from(name),data=Buffer.from(value),packed=deflateRawSync(data);let crc=0xffffffff;
    for(const byte of data){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}crc=(crc^0xffffffff)>>>0;
    const local=Buffer.alloc(30);local.writeUInt32LE(0x04034b50);local.writeUInt16LE(20,4);local.writeUInt16LE(8,8);local.writeUInt32LE(crc,14);local.writeUInt32LE(packed.length,18);local.writeUInt32LE(data.length,22);local.writeUInt16LE(filename.length,26);
    const central=Buffer.alloc(46);central.writeUInt32LE(0x02014b50);central.writeUInt16LE(20,4);central.writeUInt16LE(20,6);central.writeUInt16LE(8,10);central.writeUInt32LE(crc,16);central.writeUInt32LE(packed.length,20);central.writeUInt32LE(data.length,24);central.writeUInt16LE(filename.length,28);central.writeUInt32LE(offset,42);
    locals.push(local,filename,packed);centrals.push(central,filename);offset+=local.length+filename.length+packed.length;
  }
  const directory=Buffer.concat(centrals),end=Buffer.alloc(22);end.writeUInt32LE(0x06054b50);end.writeUInt16LE(Object.keys(files).length,8);end.writeUInt16LE(Object.keys(files).length,10);end.writeUInt32LE(directory.length,12);end.writeUInt32LE(offset,16);
  return Buffer.concat([...locals,directory,end]);
}
function workbook() {
  const esc=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
  const headers=['ID','家庭名','保護者①姓','保護者①名','保護者①電話番号','保護者①勤務先'];
  const header=headers.map((v,i)=>`<c r="${String.fromCharCode(65+i)}2" t="inlineStr"><is><t>${esc(v)}</t></is></c>`).join('');
  const sheet=`<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>保護者台帳</t></is></c></row><row r="2">${header}</row><row r="3"><c r="B3" t="inlineStr"><is><t>佐藤家</t></is></c><c r="C3" t="inlineStr"><is><t>佐藤</t></is></c><c r="D3" t="inlineStr"><is><t>花子</t></is></c><c r="E3" s="1"><v>9012345678</v></c><c r="F3"><f>UPPER(A1)</f></c></row></sheetData></worksheet>`;
  return zip({
    'xl/workbook.xml':'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="案内" sheetId="1" r:id="r1"/><sheet name="台帳" sheetId="2" r:id="r2"/></sheets></workbook>',
    'xl/_rels/workbook.xml.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="worksheets/sheet2.xml"/></Relationships>',
    'xl/worksheets/sheet1.xml':sheet,'xl/worksheets/sheet2.xml':sheet,
    'xl/styles.xml':'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="1"><numFmt numFmtId="164" formatCode="00000000000"/></numFmts><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="164"/></cellXfs></styleSheet>',
  });
}
(async()=>{
  let browser;
  try{
    let ready=false;
    for(let i=0;i<100;i++){try{ready=(await fetch(base+'/openapi.json')).ok;}catch{}if(ready)break;if(server.exitCode!==null)throw Error(log);await delay(100);}
    assert(ready,log);
    browser=await chromium.launch({channel:process.env.TEST_BROWSER_CHANNEL || 'msedge',headless:true});
    const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
    page.on('dialog',dialog=>dialog.accept());
    const errors=[],external=[],posts=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith(base))external.push(r.url());if(r.method()==='POST')posts.push(r.url());});
    await page.goto(base+'/data-transfers/converter');
    assert(await page.getByRole('heading',{name:'データ移行コンバーター',exact:true}).isVisible());
    const csv='旧園児番号,家族番号,家庭名,園児氏名,フリガナ,生年月日,入園日,クラス,保護者名①,保護者①携帯電話番号,保護者①勤務先名,備考\r\n999,F1,山田家,山田 太郎,やまだ たろう,令和4年4月1日,2025/4/1,検証クラス,山田 花子,09012345678,ひかり商店,<img src=x onerror=alert(1)>\r\n1000,F1,山田家,山田 次郎,やまだ じろう,2023/5/1,2025/4/1,検証クラス,山田 花子,09012345678,ひかり商店,兄弟\r\n';
    await page.locator('#source-file').setInputFiles({name:'old-app.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
    await page.getByRole('button',{name:'変換結果を確認する',exact:true}).waitFor();
    await page.waitForFunction(()=>!document.getElementById('convert').disabled);
    await page.locator('#family-key').selectOption({label:'B：家族番号'});
    assert.equal(await page.getByLabel('園児1 ID 元の列',{exact:true}).isEnabled(),false);
    await page.getByRole('button',{name:'変換結果を確認する',exact:true}).click();
    assert((await page.locator('#result-status').innerText()).includes('家庭 1件 / 園児 2件'));
    assert((await page.locator('#result-status').innerText()).includes('要確認 0項目'));
    assert.equal(await page.getByLabel('families row-1 保護者①姓',{exact:true}).inputValue(),'山田');
    assert.equal(await page.getByLabel('families row-1 保護者①名',{exact:true}).inputValue(),'花子');
    assert.equal(await page.getByRole('button',{name:'家庭CSVを保存',exact:true}).isEnabled(),false);
    assert((await page.locator('#result-warnings').innerText()).includes('旧園児番号'));
    await page.getByLabel('省略される列と確認事項を確認した',{exact:true}).check();
    const downloadPromise=page.waitForEvent('download');
    await page.getByRole('button',{name:'家庭CSVを保存',exact:true}).click();
    const download=await downloadPromise;
    const downloaded=fs.readFileSync(await download.path(),'utf8');
    assert(downloaded.includes('"09012345678"'));
    assert(!downloaded.includes('999'));
    assert(!downloaded.includes('<img'));
    assert.equal(posts.length,0);assert.deepEqual(external,[]);
    if(output){fs.mkdirSync(output,{recursive:true});await page.screenshot({path:path.join(output,'converter-desktop.png'),fullPage:true});await page.locator('#results').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'converter-result.png')});}
    const profilePromise=page.waitForEvent('download');await page.getByRole('button',{name:'変換設定を保存',exact:true}).click();
    const profile=fs.readFileSync(await (await profilePromise).path(),'utf8');
    assert(!profile.includes('山田')&&!profile.includes('09012345678'));
    // Application preview performs CSRF and real import validation against synthetic data.
    const familyPopupPromise=context.waitForEvent('page');
    await page.getByRole('button',{name:'家庭をアプリで事前検証',exact:true}).click();
    const familyPopup=await familyPopupPromise;await familyPopup.waitForLoadState('domcontentloaded');
    assert((await familyPopup.locator('body').innerText()).includes('検証結果'));
    await familyPopup.getByRole('button',{name:'インポート実行',exact:true}).click();
    assert((await familyPopup.locator('body').innerText()).includes('インポートを完了しました'));
    const childPopupPromise=context.waitForEvent('page');
    await page.getByRole('button',{name:'園児をアプリで事前検証',exact:true}).click();
    const childPopup=await childPopupPromise;await childPopup.waitForLoadState('domcontentloaded');
    await childPopup.getByRole('button',{name:'インポート実行',exact:true}).click();
    assert((await childPopup.locator('body').innerText()).includes('インポートを完了しました'));
    console.log('PASS: local CSV conversion, conservative IDs, household grouping, source omission review, private presets, CSRF preview and family/child import through UI');
    await familyPopup.close();await childPopup.close();
    // A changed source with the same columns can reuse a settings file.
    await page.locator('#source-file').setInputFiles({name:'another.csv',mimeType:'text/csv',buffer:Buffer.from(csv.replaceAll('山田','田中').replaceAll('やまだ','たなか'))});
    await page.waitForFunction(()=>!document.getElementById('convert').disabled);
    await page.locator('#load-profile').setInputFiles({name:'migration-settings.json',mimeType:'application/json',buffer:Buffer.from(profile)});
    await page.waitForFunction(()=>document.getElementById('family-key').value==='1');
    await page.getByRole('button',{name:'変換結果を確認する',exact:true}).click();
    assert.equal(await page.getByLabel('families row-1 家庭名',{exact:true}).inputValue(),'田中家');
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    if(output){await page.screenshot({path:path.join(output,'converter-mobile.png'),fullPage:true});await page.locator('#results').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'converter-mobile-result.png')});}
    await page.setViewportSize({width:1440,height:1000});
    // XLSX supports sheet selection, title rows, formatted zeroes, and missing formula results.
    await page.locator('#mode').selectOption('families');
    await page.locator('#source-file').setInputFiles({name:'contacts.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:workbook()});
    await page.waitForFunction(()=>!document.getElementById('convert').disabled);
    assert.equal(await page.locator('#header-row').inputValue(),'2');
    await page.locator('#source > details > summary').click();
    await page.locator('#sheet').selectOption({label:'台帳'});await page.getByRole('button',{name:'読込設定を適用',exact:true}).click();
    await page.waitForFunction(()=>!document.getElementById('convert').disabled);
    await page.getByRole('button',{name:'変換結果を確認する',exact:true}).click();
    assert.equal(await page.getByLabel('families row-1 保護者①電話番号',{exact:true}).inputValue(),'09012345678');
    assert((await page.locator('#result-issues').innerText()).includes('計算結果が保存されていません'));
    await page.getByLabel('families row-1 保護者①勤務先',{exact:true}).fill('確認済みの勤務先');
    await page.getByLabel('families row-1 保護者①勤務先',{exact:true}).press('Tab');
    assert((await page.locator('#result-status').innerText()).includes('要確認 0項目'));
    // One guardian per row is grouped only using the selected household and slot values.
    await page.locator('#mode').selectOption('guardian_rows');
    const guardianCSV='家族番号,家庭名,区分,氏名,電話番号\r\nF1,佐藤家,父,佐藤 太郎,09011112222\r\nF1,佐藤家,母,佐藤 花子,08033334444\r\n';
    const cp932=spawnSync(process.env.TEST_PYTHON || 'python',['-c','import sys;sys.stdout.buffer.write(sys.argv[1].encode("cp932"))',guardianCSV]);assert.equal(cp932.status,0);
    await page.locator('#source-file').setInputFiles({name:'guardians.csv',mimeType:'text/csv',buffer:cp932.stdout});
    await page.waitForFunction(()=>!document.getElementById('convert').disabled);
    assert((await page.locator('#source-status').innerText()).includes('Shift-JIS'));
    await page.locator('#family-key').selectOption({label:'A：家族番号'});
    await page.locator('#guardian-column').selectOption({label:'C：区分'});
    await page.locator('#guardian-first').fill('父');await page.locator('#guardian-second').fill('母');
    await page.getByRole('button',{name:'変換結果を確認する',exact:true}).click();
    assert((await page.locator('#result-status').innerText()).includes('家庭 1件　要確認 0項目'));
    assert.equal(await page.getByLabel('families row-1 保護者②名',{exact:true}).inputValue(),'花子');
    if(output){await page.locator('#results').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'guardian-rows-result.png')});}
    await page.getByRole('button',{name:'この端末の作業内容を消す',exact:true}).click();
    assert.equal(await page.locator('#source-file').inputValue(),'');
    assert.equal(await page.locator('#result-table input').count(),0);
    assert(!(await page.locator('body').textContent()).includes('確認済みの勤務先'));
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    console.log('PASS: settings reuse, responsive layout, XLSX sheet/title/zero formatting, missing formula correction, Shift-JIS guardian rows and clearing private working data');
    if(process.env.TEST_OFFLINE_FILE){
      const standalone=await context.newPage();const requests=[];const offlineErrors=[];
      standalone.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url());});standalone.on('pageerror',e=>offlineErrors.push(e.message));
      await standalone.goto(pathToFileURL(process.env.TEST_OFFLINE_FILE).href);
      await standalone.locator('#source-file').setInputFiles({name:'sample.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
      await standalone.waitForFunction(()=>!document.getElementById('convert').disabled);
      await standalone.locator('#family-key').selectOption({label:'B：家族番号'});
      await standalone.getByRole('button',{name:'変換結果を確認する',exact:true}).click();
      await standalone.getByLabel('省略される列と確認事項を確認した',{exact:true}).check();
      assert.equal(await standalone.getByRole('button',{name:'家庭をアプリで事前検証',exact:true}).count(),0);
      const promise=standalone.waitForEvent('download');await standalone.getByRole('button',{name:'家庭CSVを保存',exact:true}).click();
      assert(fs.readFileSync(await (await promise).path(),'utf8').includes('09012345678'));
      assert.deepEqual(requests,[]);assert.deepEqual(offlineErrors,[]);
      console.log('PASS: self-contained offline artifact converts and downloads without any HTTP request');
    }
  }finally{if(browser)await browser.close();server.kill();}
})().catch(error=>{console.error(error.message);console.error(error.stack?.split('\n').slice(0,8).join('\n'));process.exitCode=1;});
