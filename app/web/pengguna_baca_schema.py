"""Label/referensi pengguna dari source native; tidak mengimpor akun/DB."""
import ast
import hashlib
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import Environment,nodes

VARIANTS=('staf','staf-super','staf-detail','pelanggan','pelanggan-detail')
SOURCES=('hmu_tampilan/templates/pengguna.html','app/web/templates/pengguna_kelola.html',
    'app/web/templates/pengguna_ubah.html','app/web/templates/pengguna_pelanggan.html',
    'app/web/templates/_pengguna_jenis.html','hmu_identitas/peran.py')


def load(root):
    root=Path(root)
    paths=[root/p for p in SOURCES]
    tree=ast.parse(paths[-1].read_text())
    values={}
    def literal(node):
        if isinstance(node,ast.Constant):return node.value
        if isinstance(node,ast.Name) and node.id in values:return values[node.id]
        if isinstance(node,(ast.Tuple,ast.List)):return [literal(n) for n in node.elts]
        if isinstance(node,ast.Dict):return {literal(k):literal(v) for k,v in zip(node.keys,node.values)}
        raise ValueError('Referensi peran native berubah')
    for node in tree.body:
        if not isinstance(node,ast.Assign) or len(node.targets)!=1 or not isinstance(node.targets[0],ast.Name):continue
        if node.targets[0].id in {'OPERATOR','ADMIN','SUPERADMIN','PILIHAN','LABEL'}:values[node.targets[0].id]=literal(node.value)
    roles=[[key,values['LABEL'][key],text] for key,text in values['PILIHAN']]
    if not roles or len(roles)>8 or any(not all(type(v) is str and v for v in row) for row in roles):raise ValueError('Pilihan peran native tidak sah')
    def title(path):
        blocks=[n for n in Environment().parse((root/path).read_text()).find_all(nodes.Block) if n.name=='judul']
        if len(blocks)!=1 or len(blocks[0].body)!=1 or not isinstance(blocks[0].body[0],nodes.Output):raise ValueError('Judul native perlu review')
        output=blocks[0].body[0].nodes
        if len(output)==1 and isinstance(output[0],nodes.TemplateData):return output[0].data
        if len(output)==1 and isinstance(output[0],nodes.Getattr) and isinstance(output[0].node,nodes.Name) and output[0].node.name=='a' and output[0].attr=='nama':return '__PADI_NAMA__'
        raise ValueError('Judul pengguna native tidak dikenal')
    columns=[n.get_text() for n in BeautifulSoup((root/'app/web/templates/pengguna_pelanggan.html').read_text(),'html.parser').select('thead th')]
    if columns!=['Pelanggan','Username','Peran','Status','Kelola']:raise ValueError('Kolom akun pelanggan berubah')
    return dict(roles=roles,columns=columns,titles={'staf':title(SOURCES[0]),'staf-super':title(SOURCES[0]),'staf-detail':title(SOURCES[2]),'pelanggan':title(SOURCES[3]),'pelanggan-detail':title(SOURCES[3])},
        inputs={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
