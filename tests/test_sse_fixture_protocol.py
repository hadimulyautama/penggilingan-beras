"""Pure source contracts for the intercepted SSE scaffold, never app coverage."""
import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).parent/'pg/test_barang_masuk_bertahap_browser.py'


def comment_only(value):
    assert type(value) is str and value.endswith('\n\n') and value.strip()
    assert all(not line or line.startswith(':') for line in value.splitlines())
    assert not any(line.startswith(('data:', 'event:', 'id:', 'retry:')) for line in value.splitlines())
    return True


def source_contract():
    tree = ast.parse(SOURCE.read_text())
    constant = next(n.value for n in tree.body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id=='SSE_PROTOCOL_COMMENT' for t in n.targets))
    assert isinstance(constant, ast.Constant)
    body = ast.literal_eval(constant)
    outer = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name=='peramban')
    route = next(n for n in ast.walk(outer) if isinstance(n, ast.AsyncFunctionDef) and n.name=='route')
    branch = next(n for n in ast.walk(route) if isinstance(n, ast.If)
        and ast.unparse(n.test)=="u.path == '/api/aliran'")
    calls = [n for n in ast.walk(branch) if isinstance(n, ast.Call)
        and ast.unparse(n.func)=='route.fulfill']
    assert len(calls)==1
    kwargs = {k.arg:k.value for k in calls[0].keywords}
    assert set(kwargs)=={'status','content_type','headers','body'}
    assert ast.literal_eval(kwargs['status'])==200
    assert ast.literal_eval(kwargs['content_type'])=='text/event-stream'
    assert ast.literal_eval(kwargs['headers'])=={'Cache-Control':'no-cache'}
    assert isinstance(kwargs['body'], ast.Name) and kwargs['body'].id=='SSE_PROTOCOL_COMMENT'
    assert isinstance(branch.body[-1], ast.Return)
    return outer, body


def test_sse_scaffold_is_an_explicit_200_comment_without_any_application_dto():
    outer, body = source_contract()
    assert comment_only(body)
    metadata = next(n.value for n in ast.walk(outer) if isinstance(n, ast.Assign)
        and any(ast.unparse(t)=="transport['sse_scaffold']" for t in n.targets))
    assert isinstance(metadata, ast.Call) and isinstance(metadata.func, ast.Name) and metadata.func.id=='dict'
    values = {k.arg:ast.literal_eval(k.value) for k in metadata.keywords}
    assert values==dict(status=200, mime='text/event-stream', requests=0,
        comment_only=True, application_DTO_supplied=False, native_SSE_coverage=False)


@pytest.mark.parametrize('value', [
    'data: {}\n\n', 'event: heartbeat\n\n', 'id: 1\n\n', 'retry: 1000\n\n',
    ': comment\nnot-a-comment\n\n', ': comment\n', '', None,
])
def test_protocol_oracle_rejects_payload_fields_and_incomplete_comments(value):
    with pytest.raises(AssertionError):
        comment_only(value)


def test_sse_scaffold_retains_every_browser_pageerror_without_a_filter():
    outer, _ = source_contract()
    callbacks = [n.args[1] for n in ast.walk(outer) if isinstance(n, ast.Call)
        and ast.unparse(n.func)=='page.on' and len(n.args)==2
        and isinstance(n.args[0], ast.Constant) and n.args[0].value=='pageerror']
    assert len(callbacks)==1
    expected = ast.parse('lambda error: errors.append(str(error))', mode='eval').body
    assert ast.dump(callbacks[0])==ast.dump(expected)
    # Execute only that actual callback expression, not the PG/browser module.
    errors = []
    callback = eval(compile(ast.Expression(callbacks[0]), str(SOURCE), 'eval'), {'errors':errors})
    callback(RuntimeError('/uji/api/aliran due to access control checks.'))
    callback(TypeError('Different native failure'))
    assert errors==['/uji/api/aliran due to access control checks.', 'Different native failure']
    assert not any(isinstance(n, ast.Call) and ast.unparse(n.func) in ('errors.clear','errors.pop','errors.remove') for n in ast.walk(outer))
