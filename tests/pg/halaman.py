"""Baca data awal yang benar-benar dikirim HTML ke editor progresif."""
import json

from bs4 import BeautifulSoup


def data_awal(response, identitas):
    assert response.status_code == 200, response.text[:500]
    script = BeautifulSoup(response.text, 'html.parser').find('script', id=identitas)
    assert script and script.get('type') == 'application/json', identitas
    return json.loads(script.string)


def html_asal(response):
    """Fragmen asal giling dimasukkan browser dari JSON, bukan SSR langsung."""
    if 'id="giling-awal"' in response.text:
        return data_awal(response, 'giling-awal')['asal_html']
    return response.text
