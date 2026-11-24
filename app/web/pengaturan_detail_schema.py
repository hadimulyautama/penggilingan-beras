"""Source-only labels for six native Settings read layouts, no runtime imports."""
import ast
from pathlib import Path

PATHS=tuple('/pengaturan/'+x for x in ('peran','akses','sebab-berhenti','mutu','kledo','sistem'))
VARIANTS=('peran-lihat','peran-gudang','akses','sebab-berhenti','mutu','kledo','sistem-admin','sistem-umum')
SOURCES=('app/web/pengaturan_navigasi.py','app/web/akses.py','app/penggilingan/gudang1/services/jeda.py')


def load(root):
    root=Path(root)
    def value(path,name):
        tree=ast.parse((root/path).read_text())
        for node in tree.body:
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in node.targets):return node.value
            if isinstance(node,ast.AnnAssign) and isinstance(node.target,ast.Name) and node.target.id==name:return node.value
        raise ValueError('Native Settings reference missing: '+name)
    pages=ast.literal_eval(value(SOURCES[0],'HALAMAN'))
    columns=value(SOURCES[1],'PERAN_KOLOM')
    if not isinstance(columns,ast.Tuple):raise ValueError('Native role columns require review')
    labels=[ast.literal_eval(row.elts[1]) for row in columns.elts]
    reasons=ast.literal_eval(value(SOURCES[2],'SEBAB'))
    names=ast.literal_eval(value(SOURCES[2],'NAMA_PROSES'))
    processes=[[key,names[key]] for key in reasons]
    if not labels or not processes or len(labels)>16 or len(processes)>16:raise ValueError('Native reference shape requires review')
    return dict(pages={key:pages[key] for key in (p.rsplit('/',1)[-1] for p in PATHS)},columns=labels,processes=processes)
