(() => {
  'use strict';
  const copy=x=>JSON.parse(JSON.stringify(x));
  const classes=window.ANNUAL_PREVIEW_FIXTURES;
  const controls=['preview-rule','preview-registration','preview-state'];
  let rule='proposed',registration='both',state='new',classId=1,year=2026,nextId=100;
  const records=new Map(),key=(id,year)=>`${id}:${year}`;
  const notice=text=>{document.getElementById('preview-note').textContent=text;};
  function describe(){
    const c=classes.find(c=>c.id===classId),members=registration==='both'?[...c.teachers,'見本 管理者']:['見本 管理者'];
    const action=['legacy','approved'].includes(state)?'保存済みの担任名は保持します。下書きでは名前を直接直して保存できます。':rule==='current'?'現在の動き：担当クラスに登録された管理者も担任名に入ります。':'修正案：新規年案の担任名は管理者を除いて自動入力します。担任がいない場合は空欄にして手入力します。';
    notice(`架空の登録：${members.join('・')}。${action}`);
  }
  function create(id,schoolYear){
    const c=classes.find(c=>c.id===id),sheet=copy(c.sheet);
    const saved=['filled','legacy','approved'].includes(state),editable=state!=='approved';
    const teachers=registration==='both'?[...c.teachers]:[];
    let owner=(rule==='current'?[...teachers,'見本 管理者']:teachers).join('・');
    if(saved)owner=[...c.teachers,...(['legacy','approved'].includes(state)?['見本 管理者']:[])].join('・');
    if(['empty','partial'].includes(state))Object.values(sheet.fields).forEach((f,i)=>{if(state==='empty'||i%3!==0)f.body='';});
    const reflection=Array.from({length:4},(_,i)=>[0,1].map(()=>saved||state==='partial'&&i===0?'一人ひとりの成長を振り返った見本の文章です。':''));
    return {document_id:saved?++nextId:null,lock_version:saved?1:0,classroom_id:id,classroom_name:c.name,school_year:schoolYear,age:c.age,nursery_name:'見本保育園',owner_name:owner,sheet,editable,reflection_editable:true,status:state==='approved'?'承認済み':saved?'下書き':'未保存',sources:[{key:sheet.origin.key,title:sheet.source.source.title,year:2026,class_name:'原本の見本クラス'}],references:copy(c.references),source_error:null,previous:[{document_id:900+id,revision_id:10+id,title:`${schoolYear-1}年度 ${c.name} の見本年案`,status:'承認済み'}],reflection,reflection_periods:copy(c.reflection_periods),reflection_columns:copy(c.reflection_columns),reflection_saved_at:saved?'2026-10-12 09:00':null,reflection_states:reflection.map((values,period)=>({period,values,version:saved?1:0,locked:false,review_id:null,label:saved?'下書き':'未入力',updated_at:saved?'2026-10-12 09:00':null})),created_at:saved?'2026-10-12 09:00':null};
  }
  function context(id,schoolYear){
    const k=key(id,schoolYear);
    if(!records.has(k)){const b=create(id,schoolYear);if(b.document_id)records.set(k,copy(b));return b;}
    return copy(records.get(k));
  }
  window.AnnualOwnerMock={
    notice,
    initial(){describe();return context(classId,year);},
    reopen(boot){return context(boot.classroom_id,boot.school_year);},
    async api(route,options={},boot){
      if(route.startsWith('context?')){
        const p=new URLSearchParams(route.split('?')[1]),id=Number(p.get('classroom_id')),y=Number(p.get('school_year'));
        if(!classes.some(c=>c.id===id)||!Number.isInteger(y)||y<1900||y>2199)throw new Error('年度・クラスを確認してください。入力は保持しています。');
        classId=id;year=y;const b=context(id,y);
        if(p.has('previous_id')&&!b.document_id){b.sheet.origin={kind:'previous',document_id:Number(p.get('previous_id')),revision_id:Number(p.get('revision_id'))};b.sheet.baseline_label=`${y-1}年度の見本年案`;}
        describe();return b;
      }
      if(route==='save'){
        const p=JSON.parse(options.body);
        if(!p.owner_name.trim())throw new Error('担任名を入力してください。登録がない場合は手入力できます。');
        if(state==='error')throw new Error('保存できませんでした（確認用のエラー）。入力内容は残っています。');
        const b=copy(boot);delete b.reflection_draft;
        b.document_id=b.document_id||++nextId;b.lock_version++;b.created_at=b.created_at||'2026-10-12 09:15';b.owner_name=p.owner_name;b.status='下書き';
        for(const [id,f]of Object.entries(p.fields))b.sheet.fields[id]={...b.sheet.fields[id],...copy(f)};
        records.set(key(b.classroom_id,b.school_year),copy(b));return b;
      }
      throw new Error('この操作は見本の対象外です。');
    },
    async saveReflection(boot,values){
      if(state==='error')throw new Error('保存できませんでした（確認用のエラー）。入力内容は残っています。');
      const b=records.get(key(boot.classroom_id,boot.school_year));
      b.reflection=copy(values);b.reflection_saved_at='2026-10-12 09:20';
      b.reflection_states=values.map((v,i)=>({...b.reflection_states[i],values:copy(v),version:b.reflection_states[i].version+1,label:'下書き',updated_at:b.reflection_saved_at}));
      return copy(b.reflection_states);
    }
  };
  controls.forEach(id=>document.getElementById(id).addEventListener('change',e=>{
    if(window.AnnualOwnerMock.current?.().dirty&&!confirm('未保存の入力を取り消して、見本の状態を切り替えますか？')){
      controls.forEach((id,i)=>document.getElementById(id).value=[rule,registration,state][i]);return;
    }
    [rule,registration,state]=controls.map(id=>document.getElementById(id).value);
    records.clear();describe();window.dispatchEvent(new Event('annual-owner-reset'));
  }));
  document.getElementById('preview-reopen').addEventListener('click',()=>window.dispatchEvent(new Event('annual-owner-reopen')));
  document.addEventListener('submit',e=>e.preventDefault());
  document.addEventListener('click',e=>{
    const a=e.target.closest('a');if(!a)return;
    const href=a.getAttribute('href')||'';
    if(!['#annual-owner','#annual-plan-sheet','#annual-reflection-editor'].includes(href)){
      e.preventDefault();notice('これは架空データの確認用画面です。原本や承認画面への外部接続は行いません。');
    }
  });
})();
