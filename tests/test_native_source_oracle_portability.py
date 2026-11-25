"""Pure representation controls; shim is not a Python 3.12 runtime claim."""
import ast
import copy

import pytest

from tests.native_source_oracle import digest,fingerprint,legacy_dump_fingerprint


LEGACY_FUNCTION_DUMP=("FunctionDef(name='f', args=arguments(posonlyargs=[], "
    "args=[arg(arg='x')], kwonlyargs=[], kw_defaults=[], defaults=[]), "
    "body=[Return(value=Name(id='x', ctx=Load()))], decorator_list=[])")
SOURCE="def f(x):\n return x\nasync def g(x):\n return x\nclass C:\n pass\n"


def with_type_params(node,params):
    # Model only the extra semantic field on older Python. Do not monkeypatch
    # the actual interpreter AST classes or change their global _fields.
    fields=tuple(node._fields)
    if 'type_params' not in fields:fields+=('type_params',)
    cls=type(type(node).__name__,(type(node),),{'_fields':fields})
    result=cls()
    result.__dict__.update(copy.deepcopy(node.__dict__))
    result.type_params=copy.deepcopy(params)
    return result


def test_legacy_literal_dump_digest_is_unchanged():
    node=ast.parse(SOURCE).body[0]
    assert legacy_dump_fingerprint(node)==digest(LEGACY_FUNCTION_DUMP)


@pytest.mark.parametrize('index',[0,1,2],ids=['function','async-function','class'])
def test_empty_new_field_preserves_fixed_dump_and_json_oracles(index):
    native=ast.parse(SOURCE).body[index]
    newer=with_type_params(native,[])
    original_fields=tuple(type(native)._fields)
    before=ast.dump(newer,include_attributes=False)
    assert legacy_dump_fingerprint(newer)==legacy_dump_fingerprint(native)
    assert fingerprint(newer)==fingerprint(native)
    assert ast.dump(newer,include_attributes=False)==before
    assert newer.type_params==[] and tuple(type(native)._fields)==original_fields


@pytest.mark.parametrize('index',[0,1,2],ids=['function','async-function','class'])
def test_nonempty_generic_field_is_not_ignored(index):
    native=ast.parse(SOURCE).body[index]
    # A semantic AST payload is enough to test retention on Python 3.11;
    # this is not a parser/grammar test for Python 3.12's TypeVar class.
    generic=with_type_params(native,[ast.Name(id='T',ctx=ast.Load())])
    assert legacy_dump_fingerprint(generic)!=legacy_dump_fingerprint(native)
    assert fingerprint(generic)!=fingerprint(native)
    assert len(generic.type_params)==1


def test_native_body_and_guard_changes_remain_significant():
    native=ast.parse('@require_scope\ndef f(x):\n return x\n').body[0]
    changed=copy.deepcopy(native)
    changed.body[0].value=ast.Constant(value=0)
    assert legacy_dump_fingerprint(changed)!=legacy_dump_fingerprint(native)
    changed=copy.deepcopy(native);changed.decorator_list=[]
    assert legacy_dump_fingerprint(changed)!=legacy_dump_fingerprint(native)
