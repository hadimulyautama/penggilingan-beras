"""Actual native collection empty-state only; no product runtime/DB."""
from pathlib import Path
from jinja2 import Environment,FileSystemLoader,StrictUndefined
import pytest
ROOT=Path(__file__).parents[1]

def render(**delta):
    context=dict(mode='mesin',err='',isian={},detail=None,pengering=None,lini=[],dryer=[],jenis=[])
    return Environment(loader=FileSystemLoader(ROOT/'app/web/templates'),undefined=StrictUndefined,autoescape=True).get_template('_fasilitas_parent_empty.html').render(**{**context,**delta})

@pytest.mark.parametrize('mode,label',[('mesin','Belum ada mesin atau line produksi.'),('jenis','Belum ada jenis proses.')])
def test_actual_empty_collection_has_explicit_native_message(mode,label):
    assert label in render(mode=mode)

@pytest.mark.parametrize('delta',[{'err':'failed'},{'isian':{'nama':'draft'}},{'detail':object()},{'pengering':object()},{'lini':[object()]},{'dryer':[object()]}])
def test_not_an_error_draft_detail_or_nonempty_machine_message(delta):
    assert 'data-fasilitas-parent-empty' not in render(**delta)

def test_nonempty_processes_and_unknown_mode_are_not_empty():
    assert 'data-fasilitas-parent-empty' not in render(mode='jenis',jenis=[object()])
    assert 'data-fasilitas-parent-empty' not in render(mode='unknown')
