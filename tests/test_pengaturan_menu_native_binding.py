"""Pure source/binding checks; no product import, DB, account, or listener."""
import ast
import copy
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from starlette.requests import Request
from hmu_identitas import peran as P

SOURCE=Path(__file__).parents[1]/'app/web/pengaturan.py'
TREE=ast.parse(SOURCE.read_text())
HANDLER=next(n for n in TREE.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='halaman_pengaturan')
HELPER=next(n for n in TREE.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_metadata_menu_native')
EARLY=next(n for n in HANDLER.body if isinstance(n,ast.If) and any(
    isinstance(x,ast.ImportFrom) and x.module=='app.web.pengaturan_menu_kerangka' for x in ast.walk(n)))


def metadata_function(settings):
    # Execute just this function with native pure peran helpers. Native DB
    # predicate is an awaited callback; no whole app import or ORM surrogate.
    namespace={'settings':settings,'_P':P,'V_SUPER':P.V_SUPER}
    module=ast.Module(body=[copy.deepcopy(HELPER)],type_ignores=[])
    exec(compile(ast.fix_missing_locations(module),str(SOURCE),'exec'),namespace)
    return namespace['_metadata_menu_native']


@pytest.mark.asyncio
@pytest.mark.parametrize('view,tuan,is_super,recovery,allowed,calls',[
    (P.V_SUPER,True,True,False,True,0),
    (P.V_ADMIN,True,False,True,True,1),
    (P.V_ADMIN,True,False,False,False,1),
    (P.V_SELEPAN,False,False,True,False,0),
])
async def test_native_recovery_predicate_short_circuit_and_role_inputs(view,tuan,is_super,recovery,allowed,calls):
    count=[]
    async def native_recovery():
        count.append('actual-predicate-boundary');return recovery
    role=P.ADMIN if tuan else P.OPERATOR
    flags=await metadata_function(NS(console_website_url='https://console-fixture.invalid/',mode_uji=True))(
        view=view,peran_asli=role,tuan=tuan,is_super=is_super,sesi_pendek=False,pemulihan=native_recovery)
    assert flags['blok_kelola'] is allowed and len(count)==calls
    assert flags['blok_perusahaan'] is is_super
    assert flags['blok_lihat_sebagai']==P.admin_keatas(role)
    assert flags['blok_kerja_gudang']==P.boleh_ganti_gudang(role)
    assert flags['kelola_darurat']==(view!=P.V_SUPER)
    assert flags['blok_setelan'] is tuan
    assert flags['blok_mode_uji']==(view==P.V_SUPER)
    assert flags['mode_uji_tersedia'] is True
    assert flags['TAMPILAN_INDUK'] is True
    assert flags['sesi_pendek'] is False
    assert flags['console_url']=='https://console-fixture.invalid/console'


@pytest.mark.asyncio
async def test_non_https_console_remains_absent_without_new_config_or_role_rule():
    async def denied():return False
    flags=await metadata_function(NS(console_website_url='http://fixture.invalid',mode_uji=False))(
        view=P.V_ADMIN,peran_asli=P.ADMIN,tuan=True,is_super=False,sesi_pendek=True,pemulihan=denied)
    assert flags['console_url']=='' and flags['blok_mode_uji'] is False
    assert flags['mode_uji_tersedia'] is False and flags['sesi_pendek'] is True


class PasswordScalar(ast.NodeTransformer):
    def visit_Attribute(self,node):
        if isinstance(node.value,ast.Name) and node.value.id=='akun' and node.attr=='harus_ganti_sandi':
            return ast.copy_location(ast.Name(id='must_change',ctx=ast.Load()),node)
        return self.generic_visit(node)


def eligible(path='/pengaturan',query=b'',headers=(),must_change=False,method='GET',state=None):
    request=Request(dict(type='http',method=method,scheme='https',server=('uji',443),
                         path=path,query_string=query,headers=headers,state=state or {}))
    expr=PasswordScalar().visit(copy.deepcopy(EARLY.test))
    return eval(compile(ast.fix_missing_locations(ast.Expression(expr)),str(SOURCE),'eval'),
                {'getattr':getattr},{'request':request,'must_change':must_change})


DOC=[(b'sec-fetch-mode',b'navigate'),(b'sec-fetch-dest',b'document')]
@pytest.mark.parametrize('path',['/pengaturan','/pengaturan/sesi'])
def test_early_document_and_explicit_shell_only(path):
    assert eligible(path,headers=DOC)
    assert eligible(path,headers=[(b'x-kerangka-halaman',b'1')])
    assert not eligible(path,headers=[(b'x-pindah',b'1')])
    assert not eligible(path,headers=DOC+[(b'x-pindah',b'1')])
    assert not eligible(path)
    assert not eligible(path,headers=DOC,method='POST')
    assert not eligible(path,headers=DOC,must_change=True)
    assert not eligible(path,headers=DOC,must_change=None)
    assert not eligible(path,headers=DOC,state={'isi_halaman_bertahap':True})
    assert not eligible(path,headers=DOC,query=b'err=fixture')


@pytest.mark.parametrize('path',['/pengaturan/akun','/pengaturan/peran','/pengaturan/akses',
    '/pengaturan/perusahaan-sendiri','/pengaturan/sistem','/pelanggan/pengaturan'])
def test_other_route_families_remain_native(path):
    assert not eligible(path,headers=DOC)


def test_both_shapes_and_native_html_use_actual_caller_properties_and_dependency():
    assert 'Depends(butuh_akun)' in ast.unparse(HANDLER.args)
    calls=[node for node in ast.walk(HANDLER) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='_metadata_menu_native']
    assert len(calls)==2
    for call in calls:
        fields={k.arg:ast.unparse(k.value) for k in call.keywords}
        assert fields['is_super']=='akun.is_super'
        assert fields['sesi_pendek']=='akun.sesi_pendek'
        assert fields['tuan']=='tuan'
        assert fields['pemulihan']=='pemulihan_lama_diizinkan'
    source=ast.unparse(HANDLER)
    assert "peran_asli = getattr(request.state, 'peran_asli', None) or akun.peran" in source
    assert "if bagian == 'peran' and (not _P.boleh_ganti_gudang(peran_asli))" in source
    assert any(isinstance(node,ast.keyword) and node.arg is None and isinstance(node.value,ast.Name) and node.value.id=='menu_native' for node in ast.walk(HANDLER))
    assert ast.unparse(EARLY).count("konteks['PENGATURAN_NATIVE_FLAGS'] = menu")==1
