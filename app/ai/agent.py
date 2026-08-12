"""Agent loop (pola agentic) — menjawab pertanyaan bebas & analitik lintas-modul.

Beda dgn parser forced-tool (app.ai.base) yang 1 pesan = 1 ekstraksi:
di sini model (Sonnet) BOLEH memanggil banyak tool READ berturut-turut,
lalu menyintesis jawaban. Untuk aksi TULIS, agent tidak mengeksekusi sendiri —
ia MENGUSULKAN perintah (usulkan_perintah); bot menampilkannya & minta
konfirmasi, lalu perintah dijalankan lewat jalur deterministik yang sudah teruji.

Keamanan:
- Logika bisnis tetap di service; agent hanya MEMBACA (tool read) atau MENGUSULKAN.
- Tool keuangan hanya diberikan bila `financial=True` (staff/admin). Operator
  tak pernah menerima tool keuangan DAN laporan yang keluar tetap tanpa harga/HPP.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.ai.base import _date_context
from app.ai import guard
from app.config import settings
from app.database import SessionLocal

# ─────────────────────────── Hasil agent ───────────────────────────


@dataclass
class AgentReply:
    """Hasil satu giliran agent."""

    text: str | None = None            # jawaban final untuk ditampilkan
    propose_command: str | None = None  # perintah TULIS yang perlu dikonfirmasi
    propose_summary: str | None = None  # ringkasan manusiawi dari perintah itu


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

_WRITE_TOOL = {
    "name": "usulkan_perintah",
    "description": (
        "Gunakan bila pengguna ingin MENCATAT/MENGUBAH data (transaksi), mis. "
        "'catat packing 80 karung premium', 'beli karung 1000 lembar', "
        "'kirim 50 karung ke Toko Makmur'. JANGAN dieksekusi langsung — ajukan "
        "perintah tunggal yang JELAS & LENGKAP; sistem akan minta konfirmasi "
        "pengguna sebelum menjalankannya lewat jalur baku. Ajukan SATU perintah "
        "per usulan. Bila data kurang lengkap, JANGAN mengusulkan — tanyakan dulu."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "perintah": {
                "type": "string",
                "description": (
                    "Perintah bahasa natural yang siap dijalankan sistem, mis. "
                    "'catat packing 80 karung premium merk Imbiss laminasi 25 dari POL-...'"
                ),
            },
            "ringkasan": {
                "type": "string",
                "description": "Ringkasan singkat manusiawi tentang efek perintah ini.",
            },
        },
        "required": ["perintah", "ringkasan"],
    },
}


def _tools_for(*, financial: bool, allow_write: bool) -> list[dict]:
    tools = list(_READ_TOOLS_UMUM)
    if financial:
        tools += _READ_TOOLS_KEUANGAN
    if allow_write:
        tools.append(_WRITE_TOOL)
    return tools


def _system_prompt(*, role: str, financial: bool, allow_write: bool) -> str:
    batas_uang = (
        "Kamu BOLEH menyebut harga/HPP/nilai uang."
        if financial
        else "DILARANG menyebut harga, nilai pembelian, atau HPP — pengguna ini "
        "operator dan tidak berhak atas data keuangan. Bila ditanya soal uang, "
        "tolak sopan dan arahkan ke staff/admin."
    )
    tulis = (
        "Bila pengguna ingin MENCATAT/MENGUBAH data, panggil 'usulkan_perintah' "
        "(jangan mengaku sudah mencatat — kamu tidak mengeksekusi, hanya "
        "mengusulkan; konfirmasi ada di tangan sistem)."
        if allow_write
        else "Kamu HANYA membaca & menjawab; tidak boleh mengusulkan perubahan data."
    )
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
            from app.gudang2.service import laporan_stok_gudang2
            from app.inventory.finished_goods import (
                laporan_stok_barang_jadi, hitung_stok_bekatul,
            )
            from app.inventory.packaging import laporan_stok_kemasan
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
            from app.gudang1.services.silo import laporan_silo
            from app.gudang1.services.milling import laporan_milling
            from app.services.transfer import laporan_pk_siap_transfer
            return "\n\n".join([
                await status_gudang1(db),
                await laporan_silo(db),
                await laporan_milling(db),
                await laporan_pk_siap_transfer(db),
            ])

        if name == "status_gudang2":
            from app.gudang2.service import laporan_stok_gudang2
            from app.gudang2.polishing import laporan_penyosohan
            return "\n\n".join([
                await laporan_stok_gudang2(db, financial=financial),
                await laporan_penyosohan(db),
            ])

        if name == "stok_barang_jadi":
            from app.inventory.finished_goods import laporan_stok_barang_jadi
            from app.inventory.outgoing import laporan_barang_keluar
            return "\n\n".join([
                await laporan_stok_barang_jadi(db),
                await laporan_barang_keluar(db),
            ])

        if name == "stok_kemasan":
            from app.inventory.packaging import laporan_stok_kemasan
            return await laporan_stok_kemasan(db)

        if name == "tugas_pending":
            from app.services.report import pending_verifikasi
            return await pending_verifikasi(db)

        if name == "item_nyangkut":
            from app.services.pemantau import pemantau_nyangkut
            return await pemantau_nyangkut(db, financial=financial)

        if name == "laporan_keuangan":
            if not financial:
                return "🔒 Data keuangan hanya untuk staff/admin."
            from app.inventory.finished_goods import laporan_hpp_beras
            from app.services.transfer import laporan_transfer
            from app.services.report import laporan_pembelian_gabah
            periode = args.get("periode") or "hari_ini"
            return "\n\n".join([
                await laporan_hpp_beras(db, None),
                await laporan_transfer(db, financial=True),
                await laporan_pembelian_gabah(db, periode),
            ])

    return f"(tool '{name}' tidak dikenal)"


# ─────────────────────────── Loop agent ───────────────────────────


async def run_agent(*, text: str, role: str, financial: bool, allow_write: bool) -> AgentReply:
    """Jalankan agent (Sonnet) untuk satu pertanyaan bebas / permintaan.

    - `financial`: boleh melihat & menyebut data uang (staff/admin).
    - `allow_write`: boleh mengusulkan perintah tulis (butuh konfirmasi bot).
    """
    tools = _tools_for(financial=financial, allow_write=allow_write)
    system = _system_prompt(role=role, financial=financial, allow_write=allow_write)
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

        # Aksi tulis → hentikan loop, kembalikan usulan untuk dikonfirmasi bot.
        for tu in tool_uses:
            if tu.name == "usulkan_perintah":
                return AgentReply(
                    propose_command=(tu.input or {}).get("perintah"),
                    propose_summary=(tu.input or {}).get("ringkasan"),
                )

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
