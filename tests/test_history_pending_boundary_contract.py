"""Pure oracle for role-separated owner browser checks; no PG import/run."""
import ast
import copy
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from tests.test_riwayat_baca_saja import native_html

SOURCE=Path(__file__).resolve().parent/'pg/test_history_pending_reader_boundary_browser.py'
TREE=ast.parse(SOURCE.read_text())
FUNCTION=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='native_history_contract')
NS={'BeautifulSoup':BeautifulSoup}
exec(compile(ast.Module(body=[copy.deepcopy(FUNCTION)],type_ignores=[]),str(SOURCE),'exec'),NS)
contract=NS['native_history_contract']


@pytest.mark.parametrize('kind',['giling','sosoh'])
@pytest.mark.parametrize('editor',[False,True])
def test_contract_accepts_actual_native_role_shapes(kind,editor):
    doc=native_html(kind,admin=editor,boleh=editor)
    assert contract(str(doc),kind,editor=editor) is True


@pytest.mark.parametrize('kind',['giling','sosoh'])
def test_admin_editor_marker_cannot_be_removed_by_broad_readonly_expectation(kind):
    doc=native_html(kind,admin=True,boleh=True)
    root=doc.select_one('[data-riwayat-'+kind+']')
    del root['data-editor-perintah'];root['data-history-readonly']='1'
    with pytest.raises(AssertionError):contract(str(doc),kind,editor=True)
    with pytest.raises(AssertionError):contract(str(doc),kind,editor=False)


@pytest.mark.parametrize('kind',['giling','sosoh'])
@pytest.mark.parametrize('mutation',['legacy-marker','writer-form','qc-controller','action-trigger','duplicate-root'])
def test_operator_oracle_rejects_editor_or_unknown_action_shapes(kind,mutation):
    doc=native_html(kind);root=doc.select_one('[data-riwayat-'+kind+']')
    if mutation=='legacy-marker':root['data-editor-perintah']=''
    elif mutation=='writer-form':root.append(BeautifulSoup('<form method="post"><input name="hasil_pk"></form>','html.parser').form)
    elif mutation=='qc-controller':root.append(BeautifulSoup('<script src="/static/qc-sosoh.js?v=fixture"></script>','html.parser').script)
    elif mutation=='action-trigger':doc.select_one('script[data-buka]')['data-buka']='hasil_giling'
    else:root.insert_after(copy.deepcopy(root))
    with pytest.raises(AssertionError):contract(str(doc),kind,editor=False)


def test_owner_suite_preserves_both_penanda_barriers_role_split_and_fullnav_control():
    exercise=next(n for n in TREE.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='exercise')
    calls=[n.func.id for n in ast.walk(exercise) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
    assert calls.count('consume_native_penanda')==2
    assert calls.count('assert_pending_has_no_editor')==2
    assert calls.count('native_editor_veto_control')==1
    assert calls.count('native_readonly_nonblocking_control')==1
    assert calls.count('prepare_native_admin_draft')==1
    split=next(n for n in ast.walk(exercise) if isinstance(n,ast.If) and isinstance(n.test,ast.Name) and n.test.id=='editor')
    assert 'native_editor_veto_control' in ast.unparse(ast.Module(body=split.body,type_ignores=[]))
    assert 'native_readonly_nonblocking_control' in ast.unparse(ast.Module(body=split.orelse,type_ignores=[]))
    names=[n.name for n in TREE.body if isinstance(n,ast.AsyncFunctionDef) and n.name.startswith('test_')]
    assert len(names)==2
    for name in names:
        fn=next(n for n in TREE.body if isinstance(n,ast.AsyncFunctionDef) and n.name==name)
        markers=[ast.unparse(d) for d in fn.decorator_list]
        assert any("['navigate', 'penanda-refresh']" in d for d in markers)
        assert any("(1280, 'admin'), (390, 'operator')" in d for d in markers)
