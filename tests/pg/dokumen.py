"""Fakta dokumen tetap sama meski bahasa dan kerangka portal berbeda."""
from bs4 import BeautifulSoup


def fakta(html):
    root=BeautifulSoup(html,'html.parser').select_one('.rekap-jasa')
    assert root is not None
    def teks(el):
        return ' '.join(el.get_text(' ',strip=True).split()).replace('Beras pecah kulit (PK)','Beras PK')
    return dict(
        nomor=[teks(x) for x in root.select('.rekap-identitas strong')],
        tabel=[[teks(td) for td in tr.select('td')] for tr in root.select('.rekap-table tbody tr')],
        nilai=[teks(x) for x in root.select('dl dd')],
        pihak=[teks(x) for x in root.select('.serah-signatures strong')],
    )
