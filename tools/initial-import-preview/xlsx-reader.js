'use strict';
// Local-only XLSX reader. No formula evaluation or external resource requests.
window.readInitialWorkbook = async function(file) {
  if (file.size > 20*1024*1024) throw Error('20MB以下のExcelを選んでください。');
  const buffer = await file.arrayBuffer(), bytes = new Uint8Array(buffer), view = new DataView(buffer);
  let end = -1;
  for (let p=bytes.length-22; p>=Math.max(0,bytes.length-65557); p--) if(view.getUint32(p,true)===0x06054b50){end=p;break;}
  if(end<0) throw Error('通常の.xlsxファイルを選んでください。');
  let p=view.getUint32(end+16,true), total=0;
  const count=view.getUint16(end+10,true), entries=new Map();
  if(count>3000) throw Error('ファイルの構成が大きすぎます。');
  for(let i=0;i<count;i++){
    if(p+46>bytes.length || view.getUint32(p,true)!==0x02014b50) throw Error('Excelの圧縮形式を読み込めません。');
    const flags=view.getUint16(p+8,true), method=view.getUint16(p+10,true), size=view.getUint32(p+20,true), raw=view.getUint32(p+24,true), nl=view.getUint16(p+28,true), el=view.getUint16(p+30,true), cl=view.getUint16(p+32,true), off=view.getUint32(p+42,true);
    if(flags&1) throw Error('パスワード保護を解除したコピーを使用してください。');
    total+=raw;
    if(total>80*1024*1024 || p+46+nl+el+cl>bytes.length) throw Error('展開サイズが大きすぎるか、ファイルが壊れています。');
    const name=new TextDecoder().decode(bytes.slice(p+46,p+46+nl));
    if(entries.has(name)) throw Error('重複した内部ファイルがあります。');
    entries.set(name,{method,size,raw,off}); p+=46+nl+el+cl;
  }
  async function get(name, optional=false){
    const e=entries.get(name);
    if(!e){if(optional)return '';throw Error('Excelの必要な構成が見つかりません。');}
    if(e.off+30>bytes.length || view.getUint32(e.off,true)!==0x04034b50) throw Error('Excelの内部構成が不正です。');
    const start=e.off+30+view.getUint16(e.off+26,true)+view.getUint16(e.off+28,true);
    if(start+e.size>bytes.length) throw Error('Excelの内部構成が不正です。');
    let data=bytes.slice(start,start+e.size);
    if(e.method===8){
      if(typeof DecompressionStream==='undefined')throw Error('新しいChromeまたはEdgeで開いてください。');
      const reader=new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw')).getReader();
      const chunks=[];let length=0;
      while(true){const next=await reader.read();if(next.done)break;length+=next.value.length;if(length>e.raw || length>80*1024*1024){await reader.cancel();throw Error('展開サイズが不正です。');}chunks.push(next.value);}
      data=new Uint8Array(length);let offset=0;for(const chunk of chunks){data.set(chunk,offset);offset+=chunk.length;}
    } else if(e.method!==0) throw Error('この圧縮形式は未対応です。');
    if(data.length!==e.raw)throw Error('Excelのサイズ照合に失敗しました。');
    return new TextDecoder().decode(data);
  }
  const xml=s=>{const d=new DOMParser().parseFromString(s,'application/xml');if(d.getElementsByTagName('parsererror').length)throw Error('ExcelのXMLを読み込めません。');return d;};
  const tags=(d,t)=>Array.from(d.getElementsByTagNameNS('*',t));
  const book=xml(await get('xl/workbook.xml')), rels=xml(await get('xl/_rels/workbook.xml.rels')), stringsXml=await get('xl/sharedStrings.xml',true);
  const strings=stringsXml?tags(xml(stringsXml),'si').map(x=>tags(x,'t').map(t=>t.textContent).join('')):[];
  const relationships=new Map(tags(rels,'Relationship').filter(x=>x.getAttribute('TargetMode')!=='External').map(x=>[x.getAttribute('Id'),x.getAttribute('Target')]));
  const epoch1904=['1','true'].includes(tags(book,'workbookPr')[0]?.getAttribute('date1904'));
  const sheets=tags(book,'sheet').map(x=>({name:x.getAttribute('name'),target:relationships.get(x.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships','id'))}));
  return {sheets,async read(name){
    const sheet=sheets.find(s=>s.name===name); if(!sheet?.target)throw Error('入力用シートがありません。');
    const target=sheet.target.startsWith('/')?sheet.target.slice(1):'xl/'+sheet.target.replace(/^\.\//,'');
    const rows=tags(xml(await get(target)),'row').map(row=>{
      const values=[],formulas=[];
      for(const cell of tags(row,'c')){
        const address=cell.getAttribute('r')||'', match=address.match(/^[A-Z]+/);if(!match)throw Error('セル位置が不正です。');
        let col=0;for(const char of match[0])col=col*26+char.charCodeAt(0)-64;
        if(col>100)continue;
        const type=cell.getAttribute('t'), v=tags(cell,'v')[0]?.textContent;
        if(tags(cell,'f').length)formulas.push(col-1);
        if(type==='e')throw Error(`${row.getAttribute('r')}行目にExcelのエラーセルがあります。`);
        values[col-1]=type==='s'?(strings[Number(v)]||''):type==='inlineStr'?tags(cell,'t').map(t=>t.textContent).join(''):v===undefined?'':type==='str'?v:Number(v);
      }
      return {line:Number(row.getAttribute('r')),values,formulas};
    });
    const headers=InitialImport.fields.map(f=>f.key), header=rows.find(r=>r.values[0]===headers[0]);
    if(!header || headers.some((h,i)=>header.values[i]!==h) || header.values.slice(headers.length).some(Boolean))throw Error('列の並びまたは見出しがテンプレートと異なります。');
    const data=rows.filter(r=>r.line>header.line && r.values.some(v=>v!==''&&v!=null));
    if(data.length>1000)throw Error('試用モックは1000行までです。');
    return data.map(r=>{
      if(r.formulas.length)throw Error(`${r.line}行目に数式があります。「値のみ貼り付け」にしてください。`);
      if(r.values.slice(headers.length).some(v=>v!==''&&v!=null))throw Error(`${r.line}行目にテンプレート外の列があります。`);
      return {...Object.fromEntries(headers.map((h,i)=>[h,r.values[i]??''])),_line:r.line,_epoch1904:epoch1904};
    });
  }};
};
