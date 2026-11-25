"""Label chrome native dari template, tanpa model/DTO atau pembacaan data."""
from jinja2 import Environment, StrictUndefined, nodes


def bagian_judul(text, nilai_tetap=None):
    """Hanya literal dan atribut yang disebut caller; kode adalah slot tersendiri."""
    blocks = [n for n in Environment().parse(text).find_all(nodes.Block) if n.name == 'judul']
    if len(blocks) != 1 or any(not isinstance(n, nodes.Output) for n in blocks[0].body):
        raise ValueError('Block judul native perlu ditinjau')
    parts = []
    allowed = nilai_tetap or {}
    for output in blocks[0].body:
        for node in output.nodes:
            if isinstance(node, nodes.TemplateData):
                parts.append(node.data)
            elif isinstance(node, nodes.Const) and type(node.value) is str:
                parts.append(node.value)
            elif isinstance(node, nodes.Getattr) and isinstance(node.node, nodes.Name) and (node.node.name, node.attr) in allowed:
                parts.append(allowed[(node.node.name, node.attr)])
            else:
                raise ValueError('Ekspresi judul native belum diadopsi')
    if not parts or any(value is not None and type(value) is not str for value in parts):
        raise ValueError('Bagian judul native tidak sah')
    return parts


def judul(parts, kode):
    if type(kode) is not str or any(p is not None and type(p) is not str for p in parts):
        raise ValueError('Kode judul wajib berasal dari resource yang digate')
    return ''.join(kode if p is None else p for p in parts)


def kontrol_bar(base, *, laporan):
    """Kontrol menu/panah persis fragmen base; notifikasi tetap milik dokumen."""
    start = base.index('<header class="bar" aria-label="Navigasi aplikasi">')
    end = base.index('<span class="bar__merek"', start)
    fragment = base[start: end].split('>', 1)[1]
    html = Environment(autoescape=True, undefined=StrictUndefined).from_string(fragment).render(
        kembali='__PADI_KEMBALI__', LAPORAN_NAV=laporan)
    return html
