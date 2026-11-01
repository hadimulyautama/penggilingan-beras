"""Baca data awal yang benar-benar diberikan server ke layar interaktif."""
import json
from bs4 import BeautifulSoup


def awal(response, jenis):
    assert response.status_code == 200, response.text[:300]
    soup = BeautifulSoup(response.text, 'html.parser')
    script = soup.select_one(f'script#{jenis}-awal[type="application/json"]')
    assert script is not None, f'Data awal {jenis} tidak tersedia'
    return json.loads(script.string)
