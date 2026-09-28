"""Agent loop — menjawab pertanyaan bebas & analitik lintas-modul. BACA SAJA.

Model (Sonnet) boleh memanggil banyak tool READ berturut-turut lalu
menyintesis jawaban. Satu-satunya pemanggilnya kini `/internal/produksi/tanya`,
yaitu Kantor AI: agen ini melayani Direksi & pengawas yang BERTANYA.

Dulu ia juga bisa mengusulkan perintah tulis, yang lalu dikonfirmasi lewat bot
Telegram produksi. Pemilik membubarkan seluruh jalur itu: operasional dan
timbangan dicatat di aplikasinya masing-masing, dan satu-satunya bot yang
tersisa adalah Kantor AI. Yang mencatat bukan yang menjawab.

Keamanan:
- Logika bisnis tetap di service; agent hanya MEMBACA.
- Tool keuangan hanya diberikan bila `financial=True` (Direksi ke atas).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.ai.tanggal import _date_context
from app.ai import guard
from app.config import settings
from app.database import SessionLocal

# ─────────────────────────── Hasil agent ───────────────────────────


@dataclass
class AgentReply:
    """Hasil satu giliran agent."""

    text: str | None = None            # jawaban final untuk ditampilkan


# ─────────────────────────── Definisi tool ───────────────────────────
# Setiap tool READ: (nama, deskripsi). Eksekutor di _run_read_tool.

_READ_TOOLS_UMUM = [
    {
        "name": "ringkasan_stok",
        "description": (
            "Ringkasan stok SEMUA lini: PK Gudang 1 siap kirim, PK Gudang 2 "
            "(silo A/B + tumpukan), barang jadi (beras kemasan), bekatul curah, "
            "dan stok kemasan/karung. Pakai untuk pertanyaan stok lintas-gudang."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "status_gudang1",
        "description": (
            "Status Gudang 1: gabah/pembelian, pengeringan berjalan, isi silo G1, "
            "proses milling berjalan, PK siap kirim. Untuk pertanyaan operasional G1."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "status_gudang2",
        "description": (
            "Status Gudang 2: isi silo A/B + tumpukan PK, proses penyosohan "
            "berjalan & rendemen. Untuk pertanyaan operasional G2."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "stok_barang_jadi",
        "description": (
            "Stok barang jadi (beras kemasan per merk/ukuran/grade) + riwayat "
            "barang keluar/dikirim terakhir. Untuk pertanyaan gudang barang jadi."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "stok_kemasan",
        "description": "Stok kemasan/karung per bahan & ukuran (lembar tersisa).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "tugas_pending",
        "description": (
            "Daftar tugas tertunda yang perlu tindakan: harga gabah/PK belum "
            "diverifikasi, output milling belum di-QC, dll."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "laporan_produksi_histori",
        "description": (
            "Histori/rekap PRODUKSI per tanggal atau rentang tanggal (s/d ~1 "
            "bulan ke belakang) — untuk pertanyaan seperti 'hasil produksi 3 "
            "hari lalu', 'PK masuk minggu ini', 'produksi sebulan terakhir', "
            "'gabah & giling kemarin berapa'. Merangkum: gabah masuk (kg/batch/"
            "supplier teratas), PK masuk beli-luar, output giling (PK), output "
            "penyosohan (beras + hasil samping), dan barang keluar. TANPA harga/"
            "HPP. Untuk KEADAAN SEKARANG (stok/proses berjalan) pakai tool "
            "status/stok, bukan ini."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "periode": {
                    "type": ["string", "null"],
                    "enum": [
                        "hari_ini", "kemarin", "minggu_ini", "bulan_ini", "semua",
                        None,
                    ],
                    "description": (
                        "Rentang siap-pakai. 'hari ini'->hari_ini, 'kemarin'->"
                        "kemarin, 'minggu ini'->minggu_ini, 'bulan ini'->"
                        "bulan_ini, 'sebulan terakhir/keseluruhan'->semua. "
                        "Kosongkan bila memakai tanggal atau tgl_dari/tgl_sampai; "
                        "bila semua kosong = 30 hari terakhir."
                    ),
                },
                "tanggal": {
                    "type": ["string", "null"],
                    "description": (
                        "Satu hari SPESIFIK format YYYY-MM-DD (mis. '3 hari lalu', "
                        "'senin kemarin') — hitung dari HARI INI. null bila tidak."
                    ),
                },
                "tgl_dari": {
                    "type": ["string", "null"],
                    "description": (
                        "Awal rentang YYYY-MM-DD untuk rentang eksplisit "
                        "(mis. 'dari 1 juli sampai 31 juli'). null bila tidak."
                    ),
                },
                "tgl_sampai": {
                    "type": ["string", "null"],
                    "description": (
                        "Akhir rentang YYYY-MM-DD (inklusif). null bila tidak."
                    ),
                },
            },
        },
    },
    {
        "name": "item_nyangkut",
        "description": (
            "Item yang NYANGKUT / mandek / terlupa lintas siklus: gabah belum "
            "diproses, di dryer belum mulai pengeringan, didinginkan belum ke "
            "silo, kering di silo belum digiling, giling/penyosohan berjalan "
            "terlalu lama, PK diterima belum dimasukkan, plus verifikasi/QC "
            "tertunda (staff). Pakai untuk 'apa yang nyangkut/mandek/tertunda/"
            "perlu ditindak/mangkrak'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]

_READ_TOOLS_KEUANGAN = [
    {
        "name": "laporan_keuangan",
        "description": (
            "Data BERNILAI UANG (khusus staff/admin): HPP beras terkini, HPP PK "
            "per transfer, dan pembelian gabah beserta nilainya untuk suatu "
            "periode. Pakai untuk pertanyaan biaya/HPP/nilai pembelian."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "periode": {
                    "type": ["string", "null"],
                    "enum": ["hari_ini", "kemarin", "minggu_ini", "bulan_ini", None],
                    "description": "Periode pembelian gabah. Default hari_ini.",
                }
            },
        },
    },
]

def _tools_for(*, financial: bool) -> list[dict]:
    tools = list(_READ_TOOLS_UMUM)
    if financial:
        tools += _READ_TOOLS_KEUANGAN
    return tools


def _system_prompt(*, role: str, financial: bool) -> str:
    batas_uang = (
        "Kamu BOLEH menyebut harga/HPP/nilai uang."
        if financial
        else "DILARANG menyebut harga, nilai pembelian, atau HPP — pengguna ini "
        "operator dan tidak berhak atas data keuangan. Bila ditanya soal uang, "
        "tolak sopan dan arahkan ke staff/admin."
    )
    # Tak ada cabang "boleh menulis". Pencatatan hanya lewat Pos Produksi;
    # agen ini menjawab, dan yang menjawab tidak boleh juga yang mencatat.
    tulis = ("Kamu HANYA membaca & menjawab. Kamu TIDAK bisa mencatat atau "
             "mengubah apa pun — jangan menawarkannya, dan jangan mengaku "
             "sudah melakukannya. Bila pengguna ingin mencatat, arahkan ke "
             "Pos Produksi.")
    return (
        "Kamu asisten operasional pabrik penggilingan beras (Gudang 1 = selepan/"
        "pecah kulit, Gudang 2 = penyosohan, lalu barang jadi & pengiriman). "
        f"Peran pengguna: {role}. "
        "Jawab RINGKAS, faktual, bahasa Indonesia, pakai angka dari tool — jangan "
        "mengarang. Panggil tool READ seperlunya untuk mengumpulkan data sebelum "
        "menjawab; boleh beberapa kali. Bila data tak tersedia, katakan apa adanya. "
        f"{batas_uang} {tulis}\n\n"
        "Tanggal 14 hari terakhir (rujukan, LOOKUP jangan menghitung):\n"
        + _date_context()
    )


# ─────────────────────────── Eksekutor tool READ ───────────────────────────


async def _run_read_tool(name: str, args: dict, *, financial: bool) -> str:
    """Jalankan tool READ terhadap DB (sesi pendek), kembalikan teks laporan."""
    async with SessionLocal() as db:
        if name == "ringkasan_stok":
            from app.services.transfer import laporan_pk_siap_transfer
            from app.penggilingan.gudang2.service import laporan_stok_gudang2
            from app.penggilingan.inventory.finished_goods import (
                laporan_stok_barang_jadi, hitung_stok_bekatul,
            )
            from app.penggilingan.inventory.packaging import laporan_stok_kemasan
            bagian = [
                await laporan_pk_siap_transfer(db),
                await laporan_stok_gudang2(db, financial=financial),
                await laporan_stok_barang_jadi(db),
                f"🌾 Bekatul curah: {float(await hitung_stok_bekatul(db)):,.0f} kg".replace(",", "."),
                await laporan_stok_kemasan(db),
            ]
            return "\n\n".join(bagian)

        if name == "status_gudang1":
            from app.services.report import status_gudang1
            from app.penggilingan.gudang1.services.silo import laporan_silo
            from app.penggilingan.gudang1.services.milling import laporan_milling
            from app.services.transfer import laporan_pk_siap_transfer
            return "\n\n".join([
                await status_gudang1(db),
                await laporan_silo(db),
                await laporan_milling(db),
                await laporan_pk_siap_transfer(db),
            ])

        if name == "status_gudang2":
            from app.penggilingan.gudang2.service import laporan_stok_gudang2
            from app.penggilingan.gudang2.polishing import laporan_penyosohan
            return "\n\n".join([
                await laporan_stok_gudang2(db, financial=financial),
                await laporan_penyosohan(db),
            ])

        if name == "stok_barang_jadi":
            from app.penggilingan.inventory.finished_goods import laporan_stok_barang_jadi
            from app.penggilingan.inventory.outgoing import laporan_barang_keluar
            return "\n\n".join([
                await laporan_stok_barang_jadi(db),
                await laporan_barang_keluar(db),
            ])

        if name == "stok_kemasan":
            from app.penggilingan.inventory.packaging import laporan_stok_kemasan
            return await laporan_stok_kemasan(db)

        if name == "tugas_pending":
            from app.services.report import pending_verifikasi
            return await pending_verifikasi(db)

        if name == "item_nyangkut":
            from app.services.pemantau import pemantau_nyangkut
            return await pemantau_nyangkut(db, financial=financial)

        if name == "laporan_produksi_histori":
            from datetime import date as _date, timedelta
            from app.database import now_local
            from app.services.report import _range, laporan_produksi_histori

            def _parse(s):
                try:
                    return _date.fromisoformat(str(s)[:10]) if s else None
                except ValueError:
                    return None

            today = now_local().date()
            d1 = _parse(args.get("tgl_dari"))
            d2 = _parse(args.get("tgl_sampai"))
            hari = _parse(args.get("tanggal"))
            periode = args.get("periode")
            if d1 or d2:
                tgl_dari = d1 or d2
                tgl_sampai = d2 or d1
            elif hari:
                tgl_dari = tgl_sampai = hari
            elif periode in ("hari_ini", "kemarin", "minggu_ini", "bulan_ini"):
                tgl_dari, tgl_sampai = _range(periode)
            else:
                # 'semua'/kosong → default histori 30 hari terakhir.
                tgl_dari, tgl_sampai = today - timedelta(days=30), today
            # Batasi rentang agar tak memindai terlalu jauh (histori ~sebulan).
            if (tgl_sampai - tgl_dari).days > 366:
                tgl_dari = tgl_sampai - timedelta(days=366)
            return await laporan_produksi_histori(db, tgl_dari, tgl_sampai)

        if name == "laporan_keuangan":
            if not financial:
                return "🔒 Data keuangan hanya untuk staff/admin."
            # HPP beras DIBUANG 28 September 2026: harga keluar dari Pos
            # Produksi (keputusan pemilik). Yang tersisa di sini perpindahan
            # barang dan pembelian gabah — keduanya catatan, bukan penilaian.
            from app.services.transfer import laporan_transfer
            from app.services.report import laporan_pembelian_gabah
            periode = args.get("periode") or "hari_ini"
            return "\n\n".join([
                await laporan_transfer(db, financial=True),
                await laporan_pembelian_gabah(db, periode),
            ])

    return f"(tool '{name}' tidak dikenal)"


# ─────────────────────────── Loop agent ───────────────────────────


async def run_agent(*, text: str, role: str, financial: bool) -> AgentReply:
    """Jalankan agent (Sonnet) untuk satu pertanyaan. BACA SAJA.

    `financial`: boleh melihat & menyebut data uang (Direksi ke atas).

    Dulu ada `allow_write`: agen boleh mengusulkan perintah tulis yang lalu
    dikonfirmasi lewat bot Telegram. Pemilik membubarkannya — operasional
    dicatat di Pos Produksi, agen hanya untuk Direksi & pengawas yang bertanya.
    Kemampuan itu tidak dimatikan lewat bendera, melainkan dibuang: bendera
    yang mati cuma menunggu seseorang menyalakannya kembali.
    """
    tools = _tools_for(financial=financial)
    system = _system_prompt(role=role, financial=financial)
    messages: list[dict] = [{"role": "user", "content": text}]

    for _ in range(settings.agent_max_iterations):
        resp = await guard.panggil(
            pemanggil="agent_pabrik",
            model=settings.agent_model,
            max_tokens=1500,
            system=system,
            tools=tools,
            messages=messages,
        )
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            final = "".join(b.text for b in resp.content if b.type == "text").strip()
            return AgentReply(text=final or "Maaf, saya belum bisa menjawab itu.")

        # Eksekusi semua tool READ, umpankan hasilnya kembali.
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for tu in tool_uses:
            out = await _run_read_tool(tu.name, tu.input or {}, financial=financial)
            results.append({
                "type": "tool_result", "tool_use_id": tu.id, "content": out,
            })
        messages.append({"role": "user", "content": results})

    return AgentReply(
        text="Pertanyaannya cukup kompleks — coba persempit atau pecah jadi beberapa pertanyaan."
    )
