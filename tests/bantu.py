"""Alat bantu uji.

`kode_saja` lahir setelah tiga uji berturut-turut gagal karena alasan yang
sama: mereka memeriksa `inspect.getsource(...)` untuk memastikan bentuk lama
sudah tak dipakai, lalu tersandung KOMENTAR dan DOCSTRING fungsi itu sendiri
— yang memang menyebut bentuk lamanya untuk menerangkan mengapa ia dibuang.

Memeriksa seluruh sumber berarti menghukum penjelasan yang baik. Yang
diperiksa seharusnya kodenya saja.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Any


def kode_saja(fn: Any) -> str:
    """Sumber fungsi tanpa komentar dan tanpa docstring.

    `ast.unparse` sudah membuang komentar; docstring dibuang tersendiri karena
    ia pernyataan sungguhan, bukan komentar.
    """
    pohon = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    simpul = pohon.body[0]
    badan = getattr(simpul, "body", None)
    if (badan and isinstance(badan[0], ast.Expr)
            and isinstance(badan[0].value, ast.Constant)
            and isinstance(badan[0].value.value, str)):
        simpul.body = badan[1:]
    return ast.unparse(simpul)
