"""Warna penyajian QC saja; tidak menentukan mutu maupun mengubah nilai."""
from html import escape
import re
from reportlab.lib.colors import HexColor
from reportlab.platypus import Paragraph, TableStyle

PALET = {
    'hijau': ('#D5EBD1', '#21522A'), 'kuning': ('#FFF0AB', '#66500A'),
    'oranye': ('#FFD0A0', '#703708'), 'merah': ('#F5B5AF', '#751A16'),
    'netral': ('#F1F3F4', '#465159'),
}
PARAMETER = {'lamur', 'biji hijau', 'densiti', 'butir kuning', 'gabah', 'kandungan gabah', 'merang'}


def kode(v):
    return ' '.join(str(v).strip().lower().replace('_', ' ').replace('-', ' ').split())


def warna(parameter, nilai):
    parameter = kode(parameter)
    if parameter not in PARAMETER:
        return None
    n = kode(nilai)
    if parameter == 'lamur':
        # Dekorasi jumlah sak milik penyaji lama; tidak membaca kata global.
        n = re.split(r'\s*[·/]\s*', n)[0]
        return ('merah' if nilai is True or n in ('ya', 'ada', 'true', 'pernah lamur') else
                'hijau' if nilai is False or n in ('tidak', 'false', 'tidak ada', 'tidak lamur') else 'netral')
    if parameter == 'densiti':
        return {'empuk':'merah', 'sedang':'kuning', 'padat':'hijau'}.get(n, 'netral')
    if parameter == 'biji hijau':
        return {'tidak ada':'hijau','hampir tidak ada':'hijau','sedikit':'kuning','sedang':'oranye','banyak':'merah'}.get(n,'netral')
    return {'bersih':'hijau', 'tidak ada':'hijau', 'hampir tidak ada':'hijau',
            'sedikit':'kuning', 'sedang':'oranye', 'banyak':'merah', 'parah':'merah'}.get(n, 'netral')


class NilaiQC(str):
    def __new__(cls, parameter, nilai, teks=None):
        obj = super().__new__(cls, str(nilai if teks is None else teks))
        obj.warna = warna(parameter, nilai)
        return obj


class GabunganQC(str):
    """Bagian bertipe dalam satu sel lama, tanpa kolom atau data baru."""
    def __new__(cls, bagian, pemisah=' / '):
        obj = super().__new__(cls, pemisah.join(str(x) for x in bagian))
        obj.bagian, obj.pemisah = bagian, pemisah
        return obj


def paragraf(value, style, normalisasi=str):
    def teks(v):
        return escape(normalisasi(str(v))).replace('\n', '<br/>')
    if isinstance(value, GabunganQC):
        chunks=[]
        for x in value.bagian:
            tone=getattr(x, 'warna', None)
            chunks.append(('<font color="%s" backColor="%s">%s</font>' %
                (PALET[tone][1], PALET[tone][0], teks(x))) if tone else teks(x))
        p=Paragraph(teks(value.pemisah).join(chunks), style)
        p._qc_bagian=any(getattr(x,'warna',None) for x in value.bagian)
        return p
    p=Paragraph(teks(value), style)
    p._qc_warna=getattr(value, 'warna', None)
    if p._qc_warna:
        for f in p.frags: f.textColor=HexColor(PALET[p._qc_warna][1])
    return p


def _latar_bagian(p, style):
    def draw(table, canvas, x, y, width, height):
        # Paragraph sudah dibungkus oleh Table; gunakan baris/fragmen yang
        # benar-benar dicetak, sehingga warna tidak mengubah ukuran tabel.
        from reportlab.pdfbase.pdfmetrics import stringWidth
        top=y-style.topPadding
        lines=p.blPara.lines
        for i,line in enumerate(lines):
            cursor=x+style.leftPadding
            segments=[]
            for frag in line.words:
                text=getattr(frag, 'text', '')
                w=stringWidth(text, frag.fontName, frag.fontSize)
                segments.append((cursor,w,text,getattr(frag,'backColor',None)))
                cursor+=w
            for j,(left,w,text,bg) in enumerate(segments):
                if bg is None:continue
                # Warnai wilayah subsel nilainya tanpa mengubah geometri teks.
                start=x if j==0 else left
                end=left+w
                if not any(t.strip() for _,_,t,_ in segments[j+1:]):end=x+width
                elif segments[j+1][2].strip()=='/':end+=segments[j+1][1]/2
                if j>0 and segments[j-1][2].strip()=='/':start-=segments[j-1][1]/2
                upper=y if i==0 else top
                lower=y+height if i==len(lines)-1 else top-p.style.leading
                canvas.setFillColor(bg)
                canvas.rect(start,lower,end-start,upper-lower,stroke=0,fill=1)
            top-=p.style.leading
    return draw


def warnai_tabel(table):
    """Latar seluruh sel bertipe; kolom angka dan label biasa tidak disentuh."""
    commands=[]
    for r,row in enumerate(table._cellvalues):
        for c,cell in enumerate(row):
            if isinstance(cell, Paragraph):
                tone=getattr(cell, '_qc_warna', None)
                if tone: commands.append(('BACKGROUND',(c,r),(c,r),HexColor(PALET[tone][0])))
                elif getattr(cell, '_qc_bagian', False):
                    commands.append(('BACKGROUND',(c,r),(c,r),_latar_bagian(cell,table._cellStyles[r][c])))
    table.setStyle(TableStyle(commands))
    return table


def gaya(parameter, nilai):
    tone=warna(parameter, nilai)
    if tone is None:return ''
    bg,fg=PALET[tone]
    return f'background-color:{bg};color:{fg};print-color-adjust:exact;-webkit-print-color-adjust:exact'


def penilaian_berwarna(html):
    """Hanya nilai pada baris komponen macro QC, bukan pencarian kata halaman."""
    from bs4 import BeautifulSoup
    from markupsafe import Markup
    soup=BeautifulSoup(str(html),'html.parser')
    for row in soup.select('tr[data-komponen]'):
        cell=row.select_one('td[data-label="Hasil QC"]')
        if cell:
            value=next((str(x).strip() for x in cell.contents if isinstance(x,str) and str(x).strip()),'')
            css=gaya(row['data-komponen'],value)
            if css:cell['style']=css
    return Markup(str(soup))
