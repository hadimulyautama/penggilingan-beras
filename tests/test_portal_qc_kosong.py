"""Portal QC retains an honest empty table without changing recorded results."""
from pathlib import Path
from types import SimpleNamespace as Item

from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).resolve().parents[1] / 'app/web/templates'
ENV = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
PREFIX = '''{% macro pemeriksaan(q) %}<table class="recorded"><tbody>{% for label,nilai in q.hasil %}<tr><th>{{ label }}</th><td>{{ nilai }}</td></tr>{% endfor %}</tbody></table>{% endmacro %}'''


def render(partial, groups, kind='gabah_basah'):
    return BeautifulSoup(ENV.from_string(PREFIX + "{% include '" + partial + "' %}").render(qc_penerimaan=groups, jenis=kind), 'html.parser')


def group(rounds=(), code='GB-EXISTING'):
    return Item(kode=code, status='Sudah diperiksa' if rounds else 'Belum diperiksa', putaran=rounds, url='')


def test_portal_empty_group_retains_code_status_and_one_message_row():
    soup = render('portal/_penerimaan_qc.html', [group()])
    assert soup.select_one('.terima-qc__kepala').get_text(' ', strip=True) == 'GB-EXISTING Belum diperiksa'
    assert [x.get_text(strip=True) for x in soup.select('thead th')] == ['Parameter', 'Hasil QC']
    assert len(soup.select('tbody tr')) == 1
    cell = soup.select_one('tbody td')
    assert cell['colspan'] == '2' and cell.get_text(strip=True) == 'Belum diperiksa.'
    assert not soup.select('tbody th,input,button,form')


def test_portal_unsupported_qc_is_not_fabricated():
    soup = render('portal/_penerimaan_qc.html', [], kind='broken')
    assert len(soup.select('tbody tr')) == 1
    assert soup.select_one('tbody td').get_text(strip=True) == 'Pencatatan QC penerimaan jenis barang ini belum tersedia.'
    assert not soup.select('tbody th')


def test_recorded_rounds_and_history_remain_identical_to_shared_partial():
    rounds = [Item(hasil=[('Kadar air', '14%')]), Item(hasil=[('Kadar air', '13%')])]
    before = render('_penerimaan_qc.html', [group(rounds)])
    after = render('portal/_penerimaan_qc.html', [group(rounds)])
    assert str(after.section) == str(before.section)
    assert len(after.select('table.recorded')) == 2


def test_mixed_groups_keep_recorded_round_and_only_add_empty_group_table():
    rounds = [Item(hasil=[('Kadar air', '14%')])]
    groups = [group(rounds), group(code='GB-BELUM')]
    before = render('_penerimaan_qc.html', groups)
    after = render('portal/_penerimaan_qc.html', groups)
    assert str(after.select_one('table.recorded')) == str(before.select_one('table.recorded'))
    assert len(after.select('table.terima-nilai tbody tr')) == 1
