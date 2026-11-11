/* Menu mengikuti tombolnya, tetapi seluruh isinya harus tetap di area layar.
   Pengikat global memakai PINDAH agar tidak menumpuk saat berganti halaman. */
(function(){
 'use strict';
 const scope=document.querySelector('main.isi')||document.querySelector('.isi');if(!scope)return;
 const selector='.bk-buat-opsi,.rhs-menu-body,.dr-menu-body,.sr-design-menu-body';
 let antre=false;
 function posisikan(d){
  const menu=d.querySelector(selector),tombol=d.querySelector('summary');if(!d.open||!menu||!tombol)return;
  const v=window.visualViewport,batas={kiri:(v?.offsetLeft||0)+16,atas:(v?.offsetTop||0)+16,
   lebar:v?.width||document.documentElement.clientWidth,tinggi:v?.height||window.innerHeight};
  const kanan=batas.kiri+batas.lebar-32,bawah=batas.atas+batas.tinggi-32;
  menu.style.translate='none';menu.style.maxWidth=Math.max(0,batas.lebar-32)+'px';menu.style.maxHeight=Math.max(44,batas.tinggi-32)+'px';
  const a=tombol.getBoundingClientRect();let r=menu.getBoundingClientRect();
  const ruangBawah=bawah-a.bottom-6,ruangAtas=a.top-6-batas.atas;
  const keAtas=r.height>ruangBawah&&ruangAtas>ruangBawah;
  menu.style.maxHeight=Math.max(44,Math.min(batas.tinggi-32,keAtas?ruangAtas:ruangBawah))+'px';
  r=menu.getBoundingClientRect();
  const x=Math.max(batas.kiri,Math.min(r.left,kanan-r.width));
  const y=Math.max(batas.atas,Math.min(keAtas?a.top-6-r.height:a.bottom+6,bawah-r.height));
  menu.style.translate=(x-r.left)+'px '+(y-r.top)+'px';
 }
 function periksa(){if(antre)return;antre=true;requestAnimationFrame(()=>{antre=false;if(scope.isConnected)scope.querySelectorAll('details[open]').forEach(posisikan)});}
 function pasang(target,jenis,fn){if(window.PINDAH?.pasang)PINDAH.pasang(target,jenis,fn);else target.addEventListener(jenis,fn);}
 pasang(scope,'click',e=>{if(e.target.closest?.('summary'))periksa()});
 pasang(scope,'scroll',periksa);pasang(window,'resize',periksa);
 if(window.visualViewport){pasang(visualViewport,'resize',periksa);pasang(visualViewport,'scroll',periksa);}
 periksa();
})();
