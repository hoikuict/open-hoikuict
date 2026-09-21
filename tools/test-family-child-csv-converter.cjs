// Run with Node and Playwright installed; no network requests or real personal data.
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { deflateRawSync } = require('node:zlib');
const fs = require('node:fs');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

function testWorkbook(matrix) {
  const esc=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
  const sheet='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+matrix.map((row,i)=>`<row r="${i+1}">`+row.values.map((value,j)=>{
    const ref=String.fromCharCode(65+j)+(i+1);
    if(i===1&&j===11)return `<c r="${ref}"><f>1+1</f></c>`;
    if(i===1&&j===9)return `<c r="${ref}"><v>9012345678</v></c>`;
    return `<c r="${ref}" t="inlineStr"><is><t>${esc(value)}</t></is></c>`;
  }).join('')+'</row>').join('')+'</sheetData></worksheet>';
  const files={
    'xl/workbook.xml':'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="シート1" sheetId="1" r:id="rId1"/></sheets></workbook>',
    'xl/_rels/workbook.xml.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
    'xl/worksheets/sheet1.xml':sheet,
  };
  const locals=[],centrals=[];let offset=0;
  for(const [name,value] of Object.entries(files)){
    const filename=Buffer.from(name),data=Buffer.from(value),packed=deflateRawSync(data);let crc=0xffffffff;
    for(const byte of data){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}crc=(crc^0xffffffff)>>>0;
    const local=Buffer.alloc(30);local.writeUInt32LE(0x04034b50);local.writeUInt16LE(20,4);local.writeUInt16LE(8,8);local.writeUInt32LE(crc,14);local.writeUInt32LE(packed.length,18);local.writeUInt32LE(data.length,22);local.writeUInt16LE(filename.length,26);
    const central=Buffer.alloc(46);central.writeUInt32LE(0x02014b50);central.writeUInt16LE(20,4);central.writeUInt16LE(20,6);central.writeUInt16LE(8,10);central.writeUInt32LE(crc,16);central.writeUInt32LE(packed.length,20);central.writeUInt32LE(data.length,24);central.writeUInt16LE(filename.length,28);central.writeUInt32LE(offset,42);
    locals.push(local,filename,packed);centrals.push(central,filename);offset+=local.length+filename.length+packed.length;
  }
  const directory=Buffer.concat(centrals),end=Buffer.alloc(22);end.writeUInt32LE(0x06054b50);end.writeUInt16LE(3,8);end.writeUInt16LE(3,10);end.writeUInt32LE(directory.length,12);end.writeUInt32LE(offset,16);
  return Buffer.concat([...locals,directory,end]);
}

(async () => {
  const browser = await chromium.launch({channel: process.env.TEST_BROWSER_CHANNEL || 'msedge', headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror', error=>errors.push(error.message));
    const external=[];page.on('request', r=>{if(/^https?:/.test(r.url()))external.push(r.url());});
    await page.goto(pathToFileURL(path.resolve('tools/family-child-csv-converter.html')).href);
    const header = await page.evaluate(()=>FH);
    assert.equal(header.length,24);
    await page.locator('#schemaFile').setInputFiles({name:'family-template.csv',mimeType:'text/csv',buffer:Buffer.from('\uFEFF'+header.join(',')+'\r\n')});
    await page.waitForFunction(()=>templateVerified);
    const fixture = await page.evaluate(()=>{
      $('enroll').value='2026-04-01';
      const headers=['お子様の名前','お子様の名前（ふりがな）','生年月日','クラス','自宅住所','自宅電話番号',
        '保護者名②','保護者名②（ふりがな）','続柄②','保護者②携帯電話番号','保護者②メールアドレス','保護者②勤務先名',
        'お子様の名前②','お子様の名前（ふりがな）②','生年月日②','クラス②','お子様の名前④','お子様の名前（ふりがな）④','生年月日④','クラス③ 2'];
      const values=['検証 花子','けんしょう はなこ','2023-01-02','架空クラス','架空住所','0312345678',
        '検証 祖母','ｹﾝｼｮｳ ｿﾎﾞ','祖母','09012345678','shared@example.test','架空会社, "本社"\n2階',
        '検証 太郎','ケンショウ タロウ','2024-02-03','架空クラス','検証 次郎','ケンショウ ジロウ','2025-03-04','架空クラス'];
      const matrix=[{line:1,values:headers},{line:2,values}];
      rows=convert(matrix,false);render();return matrix;
    });
    assert.equal(await page.locator('#familySave').isEnabled(),true);
    assert.equal(await page.evaluate(()=>groups.length),1);
    assert.equal(await page.evaluate(()=>rows.length),3);
    let csvRows=await page.evaluate(()=>parseCSV(familyCSV()));
    assert.equal(csvRows[0].length,24);
    assert(csvRows[1].slice(4,14).every(x=>x===''));
    assert.equal(csvRows[1][14],'検証');
    assert.equal(csvRows[1][16],'ケンショウ');
    assert.equal(csvRows[1][20],'09012345678');
    assert.equal(csvRows[1][21],'架空会社, "本社"\n2階');
    assert(await page.evaluate(()=>rows.every(r=>r.v[11]===groups[0].name)));
    const downloadPromise=page.waitForEvent('download');await page.locator('#familySave').click();
    const download=await downloadPromise;assert.equal(download.suggestedFilename(),'01_家庭インポート.csv');
    const childDownload=page.waitForEvent('download');await page.locator('#download').click();await childDownload;
    // Numeric phone and missing cached formula require an explicit source check.
    await page.evaluate(async bytes=>{
      const file=new File([new Uint8Array(bytes)],'source.xlsx');
      const loaded=await readBook(file),matrix=await loaded.read(loaded.sheets[0].target);
      rows=convert(matrix,loaded.epoch);render();
    },[...testWorkbook(fixture)]);
    assert.equal(await page.locator('#familySave').isEnabled(),false);
    assert.match(await page.locator('#familyBody').innerText(),/先頭0/);
    assert.match(await page.locator('#familyBody').innerText(),/数式/);
    await page.getByLabel('原本で確認・修正した').check();
    assert.equal(await page.locator('#familySave').isEnabled(),true);
    // Unsplit guardian names cannot silently disappear or be inferred from a child.
    await page.evaluate(matrix=>{matrix[1].values[6]='検証祖母';rows=convert(matrix,false);render();},fixture);
    assert.equal(await page.locator('#familySave').isEnabled(),false);
    assert.match(await page.locator('#familyBody').innerText(),/検証祖母/);
    const beforeSkip=await page.evaluate(()=>({guardians:groups[0].guardians,children:rows.map(r=>r.v)}));
    const skip=page.getByLabel('姓名が未入力の保護者を無視して続ける',{exact:true});
    assert.equal(await skip.isChecked(),false);
    await skip.check();
    assert.equal(await page.locator('#familySave').isEnabled(),true);
    assert.match(await page.locator('#skipGuardianSummary').innerText(),/今回取り込まない保護者：1人/);
    assert.match(await page.locator('#skipGuardianList').innerText(),/2行・保護者②/);
    assert.equal(await page.getByLabel('2行 保護者②電話番号',{exact:true}).getAttribute('readonly'),'');
    assert.deepEqual(await page.evaluate(()=>groups[0].guardians),beforeSkip.guardians);
    assert.deepEqual(await page.evaluate(()=>rows.map(r=>r.v)),beforeSkip.children);
    // Inspect the actual saved bytes, not just the export function's return value.
    const skippedDownloadPromise=page.waitForEvent('download');
    await page.locator('#familySave').click();
    const skippedDownload=await skippedDownloadPromise;
    const savedText=fs.readFileSync(await skippedDownload.path(),'utf8');
    assert(savedText.startsWith('\uFEFF'));
    const savedRows=await page.evaluate(text=>parseCSV(text),savedText);
    assert.equal(savedRows[1].length,24);
    assert(savedRows[1].slice(4).every(value=>value===''));
    assert.equal(savedRows[1][1],await page.evaluate(()=>groups[0].name));
    const skippedChildPromise=page.waitForEvent('download');
    await page.locator('#download').click();
    const skippedChild=await skippedChildPromise;
    const savedChildren=await page.evaluate(text=>parseCSV(text),fs.readFileSync(await skippedChild.path(),'utf8'));
    assert.deepEqual(savedChildren.slice(1),beforeSkip.children);
    // Undo keeps the original fields and reinstates validation.
    await skip.uncheck();
    assert.equal(await page.locator('#familySave').isEnabled(),false);
    assert.deepEqual(await page.evaluate(()=>groups[0].guardians),beforeSkip.guardians);
    await skip.check();
    await page.locator('#download').click();
    assert.match(await page.locator('#status').innerText(),/家庭CSVを先に保存/);
    // Type surname, then click the next field without Enter/Tab. A full render on
    // blur used to detach that field, lose focus and discard the following input.
    await skip.uncheck();
    await page.getByLabel('2行 保護者②姓',{exact:true}).fill('検証');
    assert.equal(await page.evaluate(()=>groups[0].guardians[10]),'検証');
    await page.getByLabel('2行 保護者②名',{exact:true}).click();
    await page.keyboard.insertText('祖母');
    assert.equal(await page.getByLabel('2行 保護者②名',{exact:true}).inputValue(),'祖母');
    assert.equal(await page.evaluate(()=>document.activeElement.getAttribute('aria-label')),'2行 保護者②名');
    assert.equal(await page.evaluate(()=>groups[0].guardians[11]),'祖母');
    assert.doesNotMatch(await page.locator('#familyBody').innerText(),/保護者②の姓・名を入力/);
    assert.equal(await page.locator('#familySave').isEnabled(),true);
    assert.equal(await page.evaluate(()=>parseCSV(familyCSV())[1][20]),'09012345678');
    const correctedDownloadPromise=page.waitForEvent('download');
    await page.locator('#familySave').click();
    const correctedDownload=await correctedDownloadPromise;
    const correctedRows=await page.evaluate(text=>parseCSV(text),fs.readFileSync(await correctedDownload.path(),'utf8'));
    assert.deepEqual(correctedRows[1].slice(14,16),['検証','祖母']);
    // Kana normalization on blur keeps the next input focused and preserves the
    // unchanged source-reference label while the actual export uses edited data.
    await page.getByLabel('2行 保護者②姓カナ',{exact:true}).fill('けんしょう');
    await page.getByLabel('2行 保護者②名カナ',{exact:true}).click();
    await page.keyboard.insertText('そぼ');
    await page.getByLabel('2行 保護者②名カナ',{exact:true}).press('Enter');
    assert.equal(await page.getByLabel('2行 保護者②姓カナ',{exact:true}).inputValue(),'ケンショウ');
    assert.equal(await page.getByLabel('2行 保護者②名カナ',{exact:true}).inputValue(),'ソボソボ');
    assert.equal(await page.evaluate(()=>document.activeElement.getAttribute('aria-label')),'2行 保護者②名カナ');
    // Omit guardian one only; guardian two stays in its original ten columns.
    await page.evaluate(matrix=>{
      matrix[0].values.push('保護者名①','保護者名①（ふりがな）','保護者①メールアドレス','保護者①携帯電話番号');
      matrix[1].values.push('検証保護者','ケンショウホゴシャ','first@example.test','09000000000');
      rows=convert(matrix,false);render();
    },fixture);
    assert.equal(await skip.isChecked(),false);
    await skip.check();
    csvRows=await page.evaluate(()=>parseCSV(familyCSV()));
    assert(csvRows[1].slice(4,14).every(value=>value===''));
    assert.equal(csvRows[1][14],'検証');
    assert.equal(csvRows[1][19],'shared@example.test');
    assert.equal(csvRows[1][20],'09012345678');
    // Excluding children changes which guardians are counted, without clearing input.
    for(let index=0;index<3;index++)await page.locator('#body input[type=checkbox]').nth(index).uncheck();
    assert.match(await page.locator('#skipGuardianSummary').innerText(),/今回取り込まない保護者：0人/);
    assert.equal(await page.locator('#familySave').isEnabled(),false);
    await page.locator('#body input[type=checkbox]').first().check();
    assert.match(await page.locator('#skipGuardianSummary').innerText(),/今回取り込まない保護者：1人/);
    assert.equal(await page.locator('#familySave').isEnabled(),true);
    // Other guardian, source-review and child checks still apply while skipping.
    await page.getByLabel('2行 保護者②メールアドレス',{exact:true}).fill('invalid-mail');
    await page.getByLabel('2行 保護者②メールアドレス',{exact:true}).press('Tab');
    assert.equal(await page.locator('#familySave').isEnabled(),false);
    assert.match(await page.locator('#familyBody').innerText(),/保護者②のメールアドレスを確認/);
    await page.getByLabel('2行 保護者②メールアドレス',{exact:true}).fill('shared@example.test');
    await page.getByLabel('2行 保護者②メールアドレス',{exact:true}).press('Tab');
    await page.evaluate(()=>{groups[0].review=['自宅電話番号が数値です。'];render();});
    assert.equal(await page.locator('#familySave').isEnabled(),false);
    await page.getByLabel('原本で確認・修正した').check();
    await page.getByLabel('2行1人目 入園日',{exact:true}).fill('');
    await page.getByLabel('2行1人目 入園日',{exact:true}).press('Tab');
    assert.equal(await page.locator('#familySave').isEnabled(),true);
    assert.equal(await page.locator('#download').isEnabled(),false);
    await page.screenshot({path:'.local-dev/converter-guardian-skip-check.png',fullPage:true});
    // Separate answer rows never merge merely because address and phone match.
    await page.evaluate(matrix=>{matrix.push({...matrix[1],line:3});rows=convert(matrix,false);render();},fixture);
    assert.equal(await page.evaluate(()=>groups.length),2);
    assert.equal(await skip.isChecked(),false);
    await skip.check();
    assert.equal(await page.locator('#familySave').isEnabled(),false);
    // Existing child IDs, family IDs and order-two profile survive a round trip.
    await page.evaluate(matrix=>{
      knownFamilies=[['41','登録済み家庭','架空住所','0312345678',...Array(10).fill(''),'検証','祖母','ケンショウ','ソボ','祖母','shared@example.test','09012345678','既存会社','','']];
      existing=[['9','検証','花子','ケンショウ','ハナコ','2023-01-02','2026-04-01','','在園','架空クラス','41','登録済み家庭','','']];
      rows=convert(matrix,false);render();
    },fixture);
    assert.equal(await page.evaluate(()=>rows[0].v[0]),'9');
    assert.equal(await page.evaluate(()=>groups[0].id),'41');
    assert.equal(await page.locator('#familySave').isEnabled(),true);
    // Schema mismatch disables BOTH downloads even when all records are complete.
    await page.locator('#schemaFile').setInputFiles({name:'old.csv',mimeType:'text/csv',buffer:Buffer.from(header.slice(0,4).join(','))});
    await page.waitForFunction(()=>!templateVerified);
    assert.equal(await page.locator('#download').isEnabled(),false);
    assert.equal(await page.locator('#familySave').isEnabled(),false);
    await skip.check();
    assert.equal(await page.locator('#familySave').isEnabled(),false);
    assert.equal(await page.locator('#download').isEnabled(),false);
    // A failed new source load also clears omission consent and stale downloads.
    await page.locator('#file').setInputFiles({name:'invalid.xlsx',mimeType:'application/octet-stream',buffer:Buffer.from('not an xlsx')});
    await page.waitForFunction(()=>document.getElementById('message').className==='warn');
    assert.equal(await skip.isChecked(),false);
    assert.equal(await page.locator('#familySave').isEnabled(),false);
    assert.equal(await page.evaluate(()=>lastFamilyDownload),'');
    await page.screenshot({path:'.local-dev/converter-browser-check.png',fullPage:true});
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    console.log('Converter browser checks passed: 24 columns, siblings, optional guardian omission, continuous guardian editing, focus and saved corrections, undo, reload reset, validation, round trip, no network.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
