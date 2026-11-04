/* Keadaan tampilan baca saja. Tidak menyimpan token, data transaksi, atau stok. */
(function(){
'use strict';
function identitas(e){return e.tagName+':'+(e.id||e.getAttribute('data-kode-proses')||e.getAttribute('data-id')||e.getAttribute('data-kode')||e.querySelector('a[href]')?.getAttribute('href')||e.querySelector('summary')?.textContent.trim()||'');}
function keyDetail(e,i){var p=e.closest('[data-kode-proses],article,tr');return (p?identitas(p):'')+':'+(e.id||e.querySelector('summary')?.textContent.trim()||i);}
function ambil(root){
 var s={details:new Map(),fields:[],scroll:[],anchor:null,focus:null,controls:[]};
 root.querySelectorAll('details').forEach(function(e,i){s.details.set(keyDetail(e,i),e.open);});
 root.querySelectorAll('input:not([type=hidden]):not([type=password]):not([type=file]),select,textarea').forEach(function(e,i){s.fields.push({key:e.id||e.name||String(i),tag:e.tagName,type:e.type,value:e.value,checked:e.checked,selected:e.multiple?Array.from(e.selectedOptions).map(function(o){return o.value;}):null});});
 root.querySelectorAll('[aria-controls][aria-expanded],[role=tab][aria-controls]').forEach(function(e){var id=e.getAttribute('aria-controls'),panel=document.getElementById(id);if(panel&&panel.tagName!=='DIALOG')s.controls.push({id:id,expanded:e.getAttribute('aria-expanded'),selected:e.getAttribute('aria-selected'),hidden:panel.hidden});});
 var nodes=new Set([root,document.scrollingElement]);root.querySelectorAll('.isi,main,[data-scroll]').forEach(function(e){nodes.add(e);});
 for(var p=root.parentElement;p;p=p.parentElement)nodes.add(p);
 nodes.forEach(function(e){if(!e)return;s.scroll.push({node:e,selector:e.id?'#'+CSS.escape(e.id):e.matches('.isi')?'.isi':e.tagName==='MAIN'?'main':null,top:e.scrollTop,left:e.scrollLeft});});
 var scroller=s.scroll.find(function(x){return x.node.scrollHeight>x.node.clientHeight&&/auto|scroll/.test(getComputedStyle(x.node).overflowY);});
 var scrollNode=scroller?scroller.node:document.scrollingElement,top=scroller?scrollNode.getBoundingClientRect().top:0,bottom=scroller?scrollNode.getBoundingClientRect().bottom:innerHeight;
 Array.from(root.querySelectorAll('[data-kode-proses],[data-id],[data-kode],[id],article,tr,details')).some(function(e){var r=e.getBoundingClientRect();if(r.height&&r.top>=top&&r.top<bottom){s.anchor={key:identitas(e),top:r.top,scroll:scrollNode,selector:scrollNode?.id?'#'+CSS.escape(scrollNode.id):scrollNode?.matches('.isi')?'.isi':null};return true;}return false;});
 var f=document.activeElement;if(f&&root.contains(f)&&f.matches('a[href],summary'))s.focus={tag:f.tagName,key:f.getAttribute('href')||f.textContent};
 return s;
}
function pulihkan(root,s){
 if(!s)return;
 root.querySelectorAll('details').forEach(function(e,i){var k=keyDetail(e,i);if(s.details.has(k))e.open=s.details.get(k);});
 root.querySelectorAll('input:not([type=hidden]):not([type=password]):not([type=file]),select,textarea').forEach(function(e,i){var x=s.fields.find(function(v){return v.key===(e.id||e.name||String(i))&&v.tag===e.tagName&&v.type===e.type;});if(!x)return;if(x.selected)Array.from(e.options).forEach(function(o){o.selected=x.selected.includes(o.value);});else e.value=x.value;if(e.type==='checkbox'||e.type==='radio')e.checked=x.checked;});
 (s.controls||[]).forEach(function(x){var e=Array.from(root.querySelectorAll('[aria-controls]')).find(function(e){return e.getAttribute('aria-controls')===x.id;}),panel=document.getElementById(x.id);if(e&&panel&&!e.disabled){if(x.expanded!==null)e.setAttribute('aria-expanded',x.expanded);if(x.selected!==null)e.setAttribute('aria-selected',x.selected);panel.hidden=x.hidden;}});
 s.scroll.forEach(function(x){var e=x.node.isConnected?x.node:x.selector&&root.querySelector(x.selector);if(e){e.scrollTop=x.top;e.scrollLeft=x.left;}});
 if(s.anchor){var a=s.anchor,e=Array.from(root.querySelectorAll('[data-kode-proses],[data-id],[data-kode],[id],article,tr,details')).find(function(e){return identitas(e)===a.key;}),sc=a.scroll?.isConnected?a.scroll:a.selector&&root.querySelector(a.selector);if(e&&sc)sc.scrollTop+=e.getBoundingClientRect().top-a.top;}
 if(s.focus){var f=Array.from(root.querySelectorAll('a[href],summary')).find(function(e){return e.tagName===s.focus.tag&&(e.getAttribute('href')||e.textContent)===s.focus.key;});if(f)f.focus({preventScroll:true});}
}
// Cocokkan simpul berdasarkan identitas agar pendengar tombol lama tetap hidup.
function tukar(root,fresh){
 function key(e){if(e.nodeType!==1)return '';return e.id?'id:'+e.id:e.getAttribute('href')?'href:'+e.getAttribute('href'):e.getAttribute('name')?'name:'+e.tagName+':'+e.getAttribute('name')+':'+(e.getAttribute('value')||''):e.matches('tr,article')&&e.querySelector('a[href]')?'row:'+e.querySelector('a[href]').getAttribute('href'):'';}
 function morph(a,b){
  if(a.nodeType!==b.nodeType||a.nodeType===1&&a.tagName!==b.tagName)return b.cloneNode(true);
  if(a.nodeType!==1){if(a.nodeValue!==b.nodeValue)a.nodeValue=b.nodeValue;return a;}
  if(a.tagName==='SCRIPT')return a;
  Array.from(a.attributes).forEach(function(x){if(!b.hasAttribute(x.name))a.removeAttribute(x.name);});
  Array.from(b.attributes).forEach(function(x){if(a.getAttribute(x.name)!==x.value)a.setAttribute(x.name,x.value);});
  var old=Array.from(a.childNodes),used=new Set(),list=[];
  Array.from(b.childNodes).forEach(function(n,i){var k=key(n),match=k?old.find(function(o){return !used.has(o)&&key(o)===k;}):old[i]&&!used.has(old[i])&&!key(old[i])?old[i]:null;if(match){used.add(match);list.push(morph(match,n));}else if(n.nodeType!==1||n.tagName!=='SCRIPT')list.push(n.cloneNode(true));});
  list.forEach(function(n,i){if(a.childNodes[i]!==n)a.insertBefore(n,a.childNodes[i]||null);});
  while(a.childNodes.length>list.length)a.lastChild.remove();return a;
 }
 morph(root,fresh);
}
window.KEADAAN_BACA={ambil:ambil,pulihkan:pulihkan,tukar:tukar};
})();
