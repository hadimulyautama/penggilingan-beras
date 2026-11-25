/* Keep the native audit table headers on a genuine empty read only. */
(function(){'use strict';const template=document.querySelector('template[data-audit-empty-table]');if(!template)return;
 const body=template.closest('.laporan-isi');if(!body||body.querySelector('table.audit-table'))return;
 const empty=body.querySelector('.grup.daftar-standar>.kosong');if(!empty)return;
 empty.parentElement.before(template.content.cloneNode(true));empty.parentElement.remove();template.remove();
})();
