async ({expand=false}={})=>{
 const scope=document.querySelector('dialog[open]')||document;
 if(expand)scope.querySelectorAll('details').forEach(e=>e.open=true);
 const selector='a[href],button,summary,select,input:not([type="hidden"]),textarea,[aria-disabled="true"]';
 const nodes=Array.from(scope.querySelectorAll(selector));
 const findings=[];let checked=0,locked=0;
 for(let index=0;index<nodes.length;index++){
  const el=nodes[index];
  if(!el.checkVisibility({checkVisibilityCSS:true,checkOpacity:true})||el.matches('input[type=hidden]'))continue;
  if(el.closest('dialog:not([open])'))continue;
  el.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});
  await new Promise(requestAnimationFrame);
  let r=el.getBoundingClientRect();if(r.width<2||r.height<2)continue;
  if(r.top>=innerHeight||r.bottom<=0){
   el.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});
   await new Promise(requestAnimationFrame);r=el.getBoundingClientRect();
  }
  checked++;const disabled=el.matches(':disabled,[aria-disabled="true"]');if(disabled)locked++;
  const top=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
  let own=top&&(el.contains(top)||top===el);
  if(!own&&el.tagName==='A'){
   const range=document.createRange();range.selectNodeContents(el);
   own=Array.from(range.getClientRects()).some(t=>{const h=document.elementFromPoint(t.x+t.width/2,t.y+t.height/2);return h&&el.contains(h)});
  }
  const rect={x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)};
  const label=(el.innerText||el.getAttribute('aria-label')||el.getAttribute('name')||el.title||el.tagName).trim().slice(0,110);
  let cause='';
  if(r.left<-1||r.right>innerWidth+1)cause='melewati_lebar_layar';
  else if(!own&&getComputedStyle(el).pointerEvents!=='none')cause='tertutup';
  if(cause)findings.push({index,selector,label,cause,disabled,rect,tag:el.tagName,html:el.outerHTML.slice(0,800),cover:top?top.outerHTML.slice(0,600):null});
 }
 return {checked,locked,findings,overflow:document.documentElement.scrollWidth>innerWidth};
}
