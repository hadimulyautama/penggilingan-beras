"""Tes fungsi biaya LLM (murni, tanpa DB/API)."""
from app.ai.guard import est_biaya


def test_biaya_sonnet5():
    # 1M input @ $3 + 1M output @ $15 = $18
    assert round(est_biaya("claude-sonnet-5", 1_000_000, 1_000_000), 4) == 18.0


def test_biaya_haiku():
    # 2M input @ $1 = $2
    assert round(est_biaya("claude-haiku-4-5", 2_000_000, 0), 4) == 2.0


def test_biaya_model_tak_dikenal_pakai_default():
    # default (3, 15): 1M input → $3
    assert round(est_biaya("model-entah-apa", 1_000_000, 0), 4) == 3.0


def test_biaya_nol_token():
    assert est_biaya("claude-sonnet-5", 0, 0) == 0.0
