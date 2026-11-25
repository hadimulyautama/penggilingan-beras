"""Public field schema for first-click line detail; no server reader shortcut."""
import re

VARIANTS=('line','dryer')
PARENT='/pengaturan/mesin'


def deskripsi(path,query=''):
    if query or not isinstance(path,str):return None
    match=re.fullmatch(r'/pengaturan/mesin/([1-9][0-9]{0,9})',path)
    if not match or int(match[1])>2147483647:return None
    return dict(id=int(match[1]),alamat=path)


def valid_entry(entry):
    return (isinstance(entry,dict) and set(entry)=={'id','label','variant','target'}
        and type(entry['id']) is int and 0<entry['id']<=2147483647
        and isinstance(entry['label'],str) and 0<len(entry['label'])<=100
        and entry['variant'] in VARIANTS and deskripsi(entry['target'])==dict(id=entry['id'],alamat=entry['target']))


def blueprint(variant):
    """Variant flags are program shape, never an actor, live row or config."""
    if variant not in VARIANTS:return None
    return dict(variant=variant,label='__PADI_FASILITAS_LABEL__',alamat='__PADI_DATA_URL__',stamp='__PADI_STAMP__')
