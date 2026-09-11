"""Aksi cepat: membatalkan input terakhir.

**Perbedaan yang disengaja dari jalur bot.** Di bot, `undo` membatalkan lebih
dulu lalu memberi tahu apa yang barusan hilang. Di layar itu tidak cukup:
tombol yang tidak menyebutkan akibatnya akan ditekan untuk mencoba-coba, dan
yang hilang adalah catatan pekerjaan orang. Di sini yang ditawarkan justru
kalimat lengkap tentang apa yang akan dibatalkan — dan yang ditekan orang
adalah kalimat itu, bukan tombol bernama "undo".

Bentuk ini juga memakai perilaku klien yang sudah ada: bila tak ada yang bisa
dibatalkan, daftarnya kosong dan layar berkata "aksi ini belum bisa dikerjakan
sekarang" tanpa ada yang perlu ditulis di sini.

**Lingkup.** Operator hanya boleh membatalkan pekerjaannya sendiri. Staff dan
Admin boleh memilih lingkup yang lebih luas — dan lingkupnya dipilih dengan
cara yang sama: setiap lingkup ditampilkan beserta tindakan terakhirnya, jadi
memilih lingkup dan melihat akibatnya adalah satu gerakan, bukan dua.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.peran import can_see_financials
from app.database import SessionLocal, now_local
from app.models import User
from app.services import undo as svc
from app.web.aksi_umum import galat, wajib
from app.web.deps import pengguna_aksi

router = APIRouter(prefix="/miniapp", tags=["miniapp"])

#: Lingkup yang boleh dipilih staff/admin, berurutan dari yang paling sempit.
#: "saya" selalu ada dan selalu pertama — membatalkan pekerjaan sendiri adalah
#: hal yang paling sering benar, dan yang paling jarang disesali.
LINGKUP_LUAS = ("saya", "operator_gudang1", "operator_gudang2", "staff", "semua")

LINGKUP_LABEL = {
    "saya": "Saya sendiri",
    "operator_gudang1": "Operator Gudang 1",
    "operator_gudang2": "Operator Gudang 2",
    "staff": "Staff",
    "semua": "Siapa pun",
}


def _lingkup_untuk(user: User) -> tuple[str, ...]:
    return LINGKUP_LUAS if can_see_financials(user) else ("saya",)


def _kalimat(p: svc.Pratinjau) -> str:
    jam = p.waktu.strftime("%d/%m %H:%M") if p.waktu else "?"
    return f"{p.label} · {p.ringkas} · {jam} oleh {p.oleh}"


@router.get("/actions/undo-terakhir")
async def undo_terakhir(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Tindakan terakhir per lingkup yang boleh dijangkau pemakai ini.

    Yang belum didukung pembatalan otomatis TETAP ditampilkan, dengan
    keterangan — supaya orang tahu kenapa tombolnya tidak menolong, alih-alih
    mengira daftarnya rusak. Nilainya diberi awalan `x:` supaya POST menolaknya
    dengan pesan yang sama, bukan mencoba lalu gagal di tengah jalan.
    """
    pilihan: list[dict] = []
    async with SessionLocal() as db:
        for lingkup in _lingkup_untuk(user):
            try:
                ids, _ = await svc.resolve_actor_ids(
                    db, scope=lingkup, nama=None, self_id=user.id)
                p = await svc.pratinjau_terakhir(db, actor_ids=ids)
            except svc.UndoError:
                continue
            if p is None:
                continue
            awalan = LINGKUP_LABEL[lingkup]
            # Nilainya membawa ID LOG yang ditampilkan, bukan sekadar
            # lingkupnya. Tanpa itu, POST mencari "aksi terakhir" sekali lagi
            # saat mengeksekusi — dan bila ada aksi lain menyusul di antara
            # melihat dan menekan, yang dibatalkan adalah aksi itu.
            if p.didukung:
                pilihan.append({"value": f"{lingkup}:{p.log_id}",
                                "label": f"{awalan}: {_kalimat(p)}"})
            else:
                pilihan.append({
                    "value": f"x:{lingkup}",
                    "label": f"{awalan}: {_kalimat(p)} — belum bisa dibatalkan",
                })
    return pilihan


class UndoReq(BaseModel):
    lingkup: str


@router.post("/actions/undo")
async def act_undo(req: UndoReq, user: User = Depends(pengguna_aksi)) -> dict:
    mentah = (req.lingkup or "").strip()
    lingkup, _, sid = mentah.partition(":")
    log_id = int(sid) if sid.isdigit() else None
    if mentah.startswith("x:"):
        raise HTTPException(
            400,
            "Tindakan terakhir itu belum bisa dibatalkan otomatis. "
            "Mintakan koreksi ke Admin.",
        )
    # Lingkup diperiksa di sini, bukan dipercaya dari daftar tadi: daftar itu
    # disaring untuk kenyamanan, dan kenyamanan bukan pengamanan.
    wajib(lingkup in _lingkup_untuk(user),
          "Anda hanya boleh membatalkan input Anda sendiri.")

    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            ids, label = await svc.resolve_actor_ids(
                db, scope=lingkup, nama=None, self_id=user.id)
            pesan = await svc.undo_last(
                db, actor=u, actor_ids=ids, scope_label=label, log_id=log_id)
        except svc.UndoError as e:
            raise galat(e, "Gagal membatalkan input terakhir.")

    jam = now_local().strftime("%d/%m %H:%M")
    teks = f"↩️ Dibatalkan ({LINGKUP_LABEL.get(lingkup, lingkup).lower()}, {jam}):\n{pesan}"
    return {"ok": True, "pesan": pesan}


def spesifikasi(*, boleh: bool) -> list[dict]:
    """Satu aksi, ditawarkan kepada siapa pun yang boleh mencatat sesuatu."""
    if not boleh:
        return []
    return [{
        "id": "undo",
        "label": "↩️ Batalkan input terakhir",
        "post": "/miniapp/actions/undo",
        "hint": "Pilih tindakan yang mau dibatalkan — yang tertulis itulah yang "
                "akan hilang. Hanya tindakan TERAKHIR yang bisa dibatalkan; "
                "yang sebelumnya dikoreksi lewat Admin.",
        "fields": [
            {"name": "lingkup", "label": "Tindakan yang dibatalkan", "type": "remote",
             "source": "/miniapp/actions/undo-terakhir"},
        ],
    }]
