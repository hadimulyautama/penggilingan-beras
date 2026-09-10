import os, io, asyncio
from collections import defaultdict
from app.kantor.drive.client import DriveClient
from app.kantor import ocr
from app.ai.claude_client import get_client
from app.config import settings

c=DriveClient(); svc=c._service()
ROOT=os.environ["GDRIVE_ROOT_FOLDER_ID"]
DOCX="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
GDOC="application/vnd.google-apps.document"; GSHEET="application/vnd.google-apps.spreadsheet"
OUT="/private/tmp/claude-501/-Users-wahidnurhani-Developer-AI-Project/7fd8aaef-abc2-49c5-b3ef-2dc65faf1113/scratchpad/full_report.txt"

def kids(fid):
    return svc.files().list(q=f"'{fid}' in parents and trashed=false",
      fields="files(id,name,mimeType)", supportsAllDrives=True, includeItemsFromAllDrives=True, pageSize=1000).execute().get("files",[])
def media(fid): return svc.files().get_media(fileId=fid, supportsAllDrives=True).execute()

# satu walk: kumpulkan file + taksonomi (folder depth<=2) + peta path->id folder
files=[]; TAXLINES=[]; folder_by_path={}
def walk(fid, path, depth):
    ch=kids(fid)
    for f in sorted(ch,key=lambda x:x["name"]):
        p=path+"/"+f["name"]
        if f["mimeType"].endswith("folder"):
            if depth<=1: TAXLINES.append("  "*depth+"📁 "+f["name"])
            folder_by_path[p.strip("/")]=f["id"]
            walk(f["id"], p, depth+1)
        else:
            files.append({"id":f["id"],"name":f["name"],"mime":f["mimeType"],"path":p,"depth":depth})
def build():
    for f in sorted(kids(ROOT),key=lambda x:x["name"]):
        if f["mimeType"].endswith("folder") and not f["name"].startswith("_TRANSIT"):
            TAXLINES.append("📁 "+f["name"]); folder_by_path[f["name"]]=f["id"]
            walk(f["id"], "/"+f["name"], 1)
build()
TAXS="\n".join(TAXLINES)

def resolve(pathstr):
    parts=[p.strip() for p in pathstr.split("/") if p.strip()]
    return folder_by_path.get(" / ".join(parts).replace(" / ","/")) or folder_by_path.get("/".join(parts)) or _resolve_slow(parts)
def _resolve_slow(parts):
    key="/".join(parts)
    for k,v in folder_by_path.items():
        if k.endswith(key) or k.lower()=="/".join(parts).lower(): return v
    return None

async def extract(f):
    mime=f["mime"]; fid=f["id"]; nm=f["name"]
    try:
        if mime.startswith("image/"): return (await ocr.ocr_bytes(media(fid),mime,nm))[:1200]
        if mime=="application/pdf":
            t=c.unduh_teks(fid,mime,maks=1200)
            return t if (t and t.strip()) else (await ocr.ocr_bytes(media(fid),"application/pdf",nm))[:1200]
        if mime in (DOCX,GDOC,GSHEET): return c.unduh_teks(fid,mime,maks=1200)
        if mime in ("text/csv","text/plain"): return media(fid).decode("utf-8","ignore")[:1200]
        if mime==XLSX:
            import openpyxl
            wb=openpyxl.load_workbook(io.BytesIO(media(fid)),read_only=True,data_only=True); o=[]
            for ws in wb.worksheets[:2]:
                o.append("Sheet:"+ws.title)
                for row in ws.iter_rows(max_row=5,values_only=True): o.append(" | ".join(str(x) for x in row if x is not None))
            return "\n".join(o)[:1200]
    except Exception as e: return f"(gagal baca: {str(e)[:30]})"
    return ""

TOOL=[{"name":"audit","description":"Audit nama & lokasi.","input_schema":{"type":"object","properties":{
  "nama_baru":{"type":"string"},"folder_tujuan":{"type":"string"},"keyakinan":{"type":"string","enum":["tinggi","sedang","rendah"]},
  "catatan_penting":{"type":"string","description":"Fakta DURABLE penting dari isi yg layak diingat perusahaan (pihak & nilai/nomor kontrak, kewajiban, tenggat, kebijakan, keputusan). KOSONGKAN bila rutin/tak penting."},
  "anomali":{"type":"string","description":"Hal kontradiktif/janggal/tak konsisten/perlu klarifikasi (tanggal/nilai bertentangan, dokumen belum lengkap/belum ttd, nama tak cocok isi). KOSONGKAN bila tak ada."}},"required":["nama_baru","folder_tujuan","keyakinan"]}}]
SYS=("Kamu auditor arsip PT HMU. Dari ISI: (1) tentukan nama file benar (deskriptif, Title Case, tanpa 'copy'/'(1)', "
     "PERTAHANKAN ekstensi) & folder tujuan dari taksonomi (format 'Kategori / Subfolder'; 'TETAP' bila sudah benar). "
     "keyakinan 'tinggi' HANYA bila isi jelas. (2) 'catatan_penting': fakta durable penting (HANYA bila benar-benar penting; "
     "kalau rutin, kosongkan). (3) 'anomali': kontradiksi/janggal (HANYA bila ada). Jangan mengarang.")
async def audit(f,isi):
    r=await get_client().messages.create(model=settings.miniapp_model,max_tokens=300,system=SYS,
      tools=TOOL,tool_choice={"type":"tool","name":"audit"},
      messages=[{"role":"user","content":f"NAMA: {f['name']}\nLOKASI: {f['path']}\n\nISI:\n{isi[:1200]}\n\nTAKSONOMI:\n{TAXS}"}])
    for b in r.content:
        if getattr(b,"type",None)=="tool_use": return b.input or {}
    return {}

async def main():
    exe=ren=mv=flag=skip=0; per=defaultdict(list); facts=[]; anomalies=[]
    todo=[f for f in files if "/10 - Sengketa/PT. RAJAWALI/" not in f["path"]]
    for i,f in enumerate(todo):
        cat=f["path"].split("/")[1] if "/" in f["path"].strip("/") else "?"
        try:
            isi=await extract(f); d=await audit(f,isi)
        except Exception as e:
            per[cat].append(f"! ERR {f['name'][:30]}: {str(e)[:25]}"); continue
        cp=(d.get("catatan_penting") or "").strip(); an=(d.get("anomali") or "").strip()
        if cp: facts.append(f"[{f['path']}] {cp}")
        if an: anomalies.append(f"[{f['path']}] {an}")
        nb=(d.get("nama_baru") or "").strip(); ft=(d.get("folder_tujuan") or "").strip(); yk=d.get("keyakinan","rendah")
        ext=os.path.splitext(f["name"])[1]
        if nb and ext and not nb.lower().endswith(ext.lower()): nb+=ext
        if yk!="tinggi":
            flag+=1; per[cat].append(f"⚠️[{yk}] {f['path']} → nama:{nb} folder:{ft}"); continue
        acts=[]
        if nb and nb!=f["name"]:
            try: c.ganti_nama(f["id"],nb); ren+=1; acts.append(f"rename→{nb[:40]}")
            except Exception as e: acts.append(f"!rn:{str(e)[:20]}")
        if ft and ft.upper()!="TETAP" and f["depth"]<=2:
            dest=resolve(ft)
            if dest and dest!=ROOT:
                try: c.pindah(f["id"],dest); mv+=1; acts.append(f"pindah→{ft[:40]}")
                except Exception as e: acts.append(f"!mv:{str(e)[:20]}")
        elif ft and ft.upper()!="TETAP" and f["depth"]>=3:
            acts.append(f"(dalam≥3, tak dipindah; usul {ft[:30]})")
        if acts: exe+=1; per[cat].append(f"✅ {f['path']} :: {' | '.join(acts)}")
        if i%50==0:
            open(OUT,"w").write(f"progress {i}/{len(todo)} | rename {ren} pindah {mv} flag {flag}\n")
    # simpan fakta penting ke knowledge (satu dokumen konsolidasi)
    ksave="(tak ada)"
    if facts:
        try:
            from app.kantor import pengetahuan as P
            isi_k=("Fakta penting yang terkumpul saat audit arsip Drive (dibaca dari isi file). "
                   "Setiap baris: [lokasi file] fakta.\n\n"+"\n".join(facts[:400]))
            await P.simpan(judul="Fakta Penting dari Audit Arsip Drive", isi=isi_k)
            ksave=f"{len(facts)} fakta disimpan"
        except Exception as e:
            ksave=f"(gagal simpan knowledge: {str(e)[:60]}); {len(facts)} fakta ada di laporan"
    with open(OUT,"w") as w:
        w.write(f"SELESAI. total {len(todo)} | RENAME {ren} | PINDAH {mv} | DITANDAI {flag} | KNOWLEDGE: {ksave}\n\n")
        for cat in sorted(per):
            w.write(f"\n===== {cat} =====\n"+"\n".join(per[cat])+"\n")
        w.write("\n\n===== ANOMALI / KONTRADIKSI (untuk ditanyakan) =====\n")
        w.write("\n".join(anomalies) if anomalies else "(tak ada)")
        w.write("\n\n===== FAKTA PENTING (masuk knowledge) =====\n")
        w.write("\n".join(facts) if facts else "(tak ada)")
    print(f"RENAME {ren} | PINDAH {mv} | DITANDAI {flag} | {ksave} | anomali {len(anomalies)} → {OUT}")
asyncio.run(main())
