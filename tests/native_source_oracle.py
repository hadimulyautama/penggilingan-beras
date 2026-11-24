"""Fixed native-source proofs usable in sealed exports and shallow checkouts.

Baseline provenance is recorded once, not read from mutable HEAD at test time.
No application module, Git, database or command is imported by this helper.
"""
import ast
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value,str) else value).hexdigest()


def _shape(value):
    if isinstance(value,ast.AST):
        return [type(value).__name__,[[key,_shape(item)] for key,item in ast.iter_fields(value)
            if key not in {'lineno','end_lineno','col_offset','end_col_offset'} and not (key=='type_params' and not item)]]
    if isinstance(value,(list,tuple)):return [_shape(item) for item in value]
    if value is Ellipsis:return ['literal','Ellipsis']
    if isinstance(value,bytes):return ['literal-bytes',value.hex()]
    if isinstance(value,complex):return ['literal-complex',repr(value)]
    return value


def fingerprint(value):
    return digest(json.dumps(_shape(value),ensure_ascii=True,separators=(',',':')))


def baseline(group):
    raw=(Path(__file__).parent/'fixtures/native_source_oracles/baseline.json').read_bytes()
    assert digest(raw)=='0592d4c20170ac1586d073c3212b0124e728639947b6c949b02bb189ed3bd06e'
    receipt=json.loads(raw)
    assert receipt['version']==1
    assert receipt['fingerprint_format']=='ast-fields-json-v1: no positions; omit empty Python>=3.12 type_params only'
    return receipt[group]


def functions(source):
    nodes=[n for n in ast.parse(source).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
    result={n.name:n for n in nodes}
    assert len(result)==len(nodes), 'Duplicate native function definition'
    return result


def native_render_boundary(function):
    for index,node in enumerate(function.body):
        call=node.value if isinstance(node,(ast.Assign,ast.Return)) else None
        if isinstance(call,ast.Await):call=call.value
        if isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id in {'render','render_laci'}:
            return fingerprint([function.body[:index],call])
    raise AssertionError('Native render boundary missing')


def remove_declared_shape(function,module,expected):
    nodes=[node for node in function.body if isinstance(node,ast.ImportFrom) and node.module==module
        or isinstance(node,ast.If) and ast.unparse(node.test)=='permintaan_kerangka(request)']
    assert len(nodes)==2
    assert fingerprint(ast.Module(body=nodes,type_ignores=[]))==expected
    function.body=[node for node in function.body if node not in nodes]
