"""Allow independent sample states in the multi-form QR article."""
from pathlib import Path
p=Path(__file__).resolve().parent/'dist/app.js'
js=p.read_text(encoding='utf-8')
start=js.index('function renderStep(');end=js.index('function article(',start)
js=js[:start]+'''function renderStep(a,i,print=false){
  const s=a.steps[i], prefix=s.imagePrefix||a.imagePrefix||(currentArticle==='phone'?'phone':'monthly');
  const selected=!print&&s.states?(imageState[i]||s.states[0][0]):'';
  const image=selected?prefix+'-'+selected:s.image;
  const caption=selected?s.stateNotes[selected]:s.alt;
  const calls=selected&&s.stateCalls&&Object.hasOwn(s.stateCalls,selected)?s.stateCalls[selected]:s.calls;
  return `<section class="step-body" id="${print?'print-':''}step-${i}"><div class="step-heading"><span class="number">${i+1}</span><h2>${s.title}</h2></div><p>${prose(s.text)}</p>${s.states&&!print?`<label class="state-select">見本の状態 <select data-state-step="${i}" aria-label="見本の状態">${s.states.map(([v,l])=>`<option value="${v}"${selected===v?' selected':''}>${l}</option>`).join('')}</select></label><p class="state-explanation">${prose(s.stateNotes[selected])}</p>`:''}${image?`<figure class="screen${s.focused?' screen-focused':''}${s.compact?' screen-compact':''}" data-frame="${s.focused||s.compact?s.image:''}"><button type="button" data-zoom="${image}" data-caption="${esc(caption)}" aria-label="手順${i+1}の画面を拡大"><img width="${screenshotSizes[image][0]}" height="${screenshotSizes[image][1]}" src="assets/${image}.jpg" alt="${esc(caption)}"></button><figcaption><span>${s.diagram?'操作の図（実機のスクリーンショットではありません）':s.compact?'配備版の画面を使った見本・設定状態は説明用です':a.audience==='parents'?'画面の見本。名前や時刻は例です。':'配備記録に対応する画面の見本・架空データ'}${['monthly-empty','monthly-filled','monthly-confirm','monthly-error','monthly-history'].includes(image)?'／入力欄を縦に展開':''}</span><span>画像を押すと拡大 ↗</span></figcaption></figure>`:''}${calls?.length?`<ol class="callouts">${calls.map((c,k)=>`<li><span class="number">${k+1}</span><span>${prose(c)}</span></li>`).join('')}</ol>`:''}${s.note?`<div class="notice ${i===a.steps.length-2?'warm':''}">${prose(s.note)}</div>`:''}</section>`;
}
'''+js[end:]
js=js.replace("imageState=''","imageState={}")
js=js.replace("imageState=s.value;updateReader();main.querySelector('[data-state-step]').focus({preventScroll:true});", "imageState={...imageState,[s.dataset.stateStep]:s.value};const step=s.dataset.stateStep;updateReader();main.querySelector(`[data-state-step=\"${step}\"]`).focus({preventScroll:true});")
p.write_text(js,encoding='utf-8')
