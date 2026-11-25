"""Source/gate checks for native caller integration; no app/DB/ORM execution."""
import ast
from pathlib import Path
import pytest
from starlette.requests import Request
ROOT=Path(__file__).parents[1]
TREE=ast.parse((ROOT/'app/web/layar_jasa.py').read_text())
DETAIL=next(n for n in TREE.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='detail_pelanggan')
EARLY=next(n for n in DETAIL.body if isinstance(n,ast.If) and any(isinstance(x,ast.ImportFrom) and x.module=='app.web.jasa_detail_kerangka' for x in ast.walk(n)))


def test_caller_guard_order_and_catalog_only_after_native_context_read():
    guards=[n for n in DETAIL.body if isinstance(n,ast.If)]
    assert guards.index(EARLY)>0
    assert 'can_see_financials(akun.user)' in ast.unparse(guards[0])
    assert "raise HTTPException(422, 'Tab pelanggan tidak dikenal.')" in ast.unparse(guards[1])
    assert 'Depends(butuh_akun)' in ast.unparse(DETAIL.args)
    for name in ('halaman_jasa','detail_pelanggan'):
        function=next(n for n in TREE.body if isinstance(n,ast.AsyncFunctionDef) and n.name==name)
        assert ast.unparse(function.body[-1])=='return pasang(request, akun, response)'
        assert any(isinstance(n,ast.Assign) and isinstance(n.value,ast.Await) and isinstance(n.value.value,ast.Call) and isinstance(n.value.value.func,ast.Name) and n.value.value.func.id=='render_laci' for n in function.body)


@pytest.mark.parametrize('headers,portal,expected',[
    ([(b'sec-fetch-mode',b'navigate'),(b'sec-fetch-dest',b'document')],False,True),
    ([(b'x-kerangka-halaman',b'1')],False,True),
    ([(b'x-pindah',b'1')],False,False),
    ([(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'1')],False,False),
    ([(b'x-kerangka-halaman',b'1')],True,False),([],False,False),
])
def test_native_data_xpindah_always_wins_and_portal_is_not_adopted(headers,portal,expected):
    request=Request(dict(type='http',method='GET',scheme='https',server=('uji',443),path='/jasa/pelanggan/17',query_string=b'',headers=headers,state={}))
    actual=eval(compile(ast.Expression(EARLY.test),'<native-jasa-gate>','eval'),{'is_customer_read':lambda _:portal},{'request':request})
    assert actual is expected
