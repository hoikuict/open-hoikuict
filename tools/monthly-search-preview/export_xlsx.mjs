import fs from 'node:fs/promises';
import path from 'node:path';
import {SpreadsheetFile, Workbook} from '@oai/artifact-tool';

const [input, output, render] = process.argv.slice(2);
const layout = JSON.parse(await fs.readFile(input, 'utf8'));
const workbook = Workbook.create();
for (const [index, page] of layout.pages.entries()) {
  const sheet = workbook.worksheets.add(`月案${String(index+1).padStart(2,'0')}`);
  sheet.showGridLines = false;
  const area = sheet.getRangeByIndexes(0,0,layout.rows,layout.columns);
  area.format.font = {name:'Meiryo',size:layout.font_size,color:'#18221C'};
  area.format.rowHeight = layout.row_height;
  area.format.columnWidthPx = layout.width / layout.columns * 96 / 72;
  area.format.wrapText = true;
  area.format.verticalAlignment = 'top';
  area.format.horizontalAlignment = 'left';
  for (const cell of page.cells) {
    const range = sheet.getRangeByIndexes(cell.row,cell.col,cell.height,cell.span);
    range.merge();
    // Literal values only: a user's leading = must never become an Excel formula.
    const displayText = cell.lines.join('\n');
    range.values = [[displayText.startsWith('=') ? "'"+displayText : displayText]];
    range.format.font = {name:'Meiryo',size:cell.font_size,color:'#18221C',bold:cell.style==='title'};
    if(cell.style !== 'title') range.format.borders = {preset:'outside',style:'thin',color:'#617168'};
    if(cell.style==='label') { range.format.fill='#F0F3F1'; range.format.horizontalAlignment='center'; }
    if(cell.style==='name') range.format.horizontalAlignment='center';
  }
}
workbook.recalculate();
const first = await workbook.inspect({kind:'table',range:'月案01!A1:BT14',include:'values,formulas',tableMaxRows:3,tableMaxCols:5,maxChars:1000});
const formulas = await workbook.inspect({kind:'formula',options:{maxResults:5},maxChars:1000});
await fs.writeFile(path.join(path.dirname(output),'xlsx-check.json'),JSON.stringify({first:first.ndjson,formulas:formulas.ndjson}));
if(render==='--render') {
  for(let i=0;i<layout.pages.length;i++) {
    const picture = await workbook.render({sheetName:`月案${String(i+1).padStart(2,'0')}`,range:'A1:BT85',scale:1.4,format:'png'});
    await fs.writeFile(path.join(path.dirname(output),`excel-${i+1}.png`),new Uint8Array(await picture.arrayBuffer()));
  }
}
await (await SpreadsheetFile.exportXlsx(workbook)).save(output);
