"""Definisi tool-use Claude untuk ekstraksi data pembelian gabah."""
from __future__ import annotations

# Tool tunggal untuk Fase 1: mengekstrak data fisik pembelian gabah dari
# kalimat bebas operator. Semua field opsional — jika tidak disebut, biarkan
# null; backend/bot yang akan menanyakan kekurangannya satu per satu.
CATAT_PEMBELIAN_GABAH = {
    "name": "catat_pembelian_gabah",
    "description": (
        "Ekstrak data pembelian gabah dari pesan operator gudang penggilingan "
        "beras berbahasa Indonesia (termasuk gaya santai/singkat). Satu truk = "
        "satu batch. Jika sebuah data tidak disebutkan, JANGAN mengarang — "
        "kembalikan null untuk field itu."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_pembelian_gabah": {
                "type": "boolean",
                "description": (
                    "true jika pesan bermaksud mencatat pembelian atau kedatangan "
                    "gabah masuk — dikenali dari MAKNA (ada penjual/supplier "
                    "dan/atau berat gabah), TANPA harus ada kata persis 'gabah "
                    "masuk'. Deteksi dari makna, bukan kata kunci. Contoh yang "
                    "HARUS true: 'gabah masuk dari pak budi 8 ton', "
                    "'beli gabah 8 ton dari catur', 'masuk 8ton dari hasan plat "
                    "B1234XY', 'dari pak budi 8 ton basah', 'terima gabah 5 kwintal "
                    "bu siti'. false untuk pertanyaan/laporan/sapaan."
                ),
            },
            "nama_supplier": {
                "type": ["string", "null"],
                "description": "Nama supplier/penjual gabah. Contoh: 'Pak Budi'.",
            },
            "berat_kg": {
                "type": ["number", "null"],
                "description": (
                    "Berat total gabah dalam KILOGRAM. Konversi ton ke kg "
                    "(1 ton = 1000 kg). '8 ton' -> 8000. '8500 kg' -> 8500."
                ),
            },
            "kondisi_gabah": {
                "type": ["string", "null"],
                "enum": ["basah", "kering", None],
                "description": (
                    "Kondisi gabah. Jika operator tidak menyebut, kembalikan "
                    "null (backend memakai default 'basah')."
                ),
            },
            "no_polisi_truk": {
                "type": ["string", "null"],
                "description": "Nomor polisi truk. Contoh: 'B 1234 XY'.",
            },
            "kadar_air_awal_persen": {
                "type": ["number", "null"],
                "description": "Kadar air awal dalam persen jika disebut. '13%' -> 13.",
            },
        },
        "required": ["is_pembelian_gabah"],
    },
}

SYSTEM_PROMPT = (
    "Kamu adalah asisten pencatatan untuk usaha penggilingan beras. Tugasmu "
    "mengekstrak data terstruktur dari pesan pengguna lapangan. Selalu panggil "
    "tool yang tersedia. "
    "Pengguna menulis dengan bahasa Indonesia sehari-hari: santai, singkat, "
    "banyak singkatan dan typo, sering tanpa tanda baca. Pahami MAKSUD dari "
    "makna kalimat, jangan mengandalkan kata kunci yang persis. Bersikaplah "
    "MURAH HATI dalam mengenali maksud: kalau pesan masuk akal sebagai tugas "
    "yang tool ini tangani, tandai boolean niatnya true. "
    "Tetap jangan mengarang nilai data yang tidak disebutkan pengguna — untuk "
    "field data gunakan null bila tidak ada. Pahami satuan Indonesia: ton, kg, "
    "kwintal (1 kwintal = 100 kg); dan uang: juta/jt, ribu/rb, titik sebagai "
    "pemisah ribuan."
)


# Tool tanya laporan pembelian gabah (Gudang 1 & Admin).
TANYA_LAPORAN_GABAH = {
    "name": "tanya_laporan_gabah",
    "description": (
        "Deteksi bila pengguna BERTANYA tentang ringkasan/laporan pembelian "
        "gabah masuk (berapa banyak, berapa batch, dari supplier mana). "
        "Contoh yang HARUS true: 'berapa gabah masuk hari ini', "
        "'total gabah hari ini berapa', 'gabah masuk minggu ini', "
        "'laporan pembelian gabah', 'hari ini beli gabah berapa ton'. "
        "Bedakan dari perintah MENCATAT pembelian (itu bukan pertanyaan)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_laporan_gabah": {
                "type": "boolean",
                "description": (
                    "true jika pesan adalah PERTANYAAN tentang laporan/ringkasan "
                    "gabah masuk. false untuk perintah pencatatan atau hal lain."
                ),
            },
            "periode": {
                "type": ["string", "null"],
                "enum": ["hari_ini", "kemarin", "minggu_ini", "bulan_ini", "semua", None],
                "description": (
                    "Rentang waktu yang ditanyakan. 'hari ini'->hari_ini, "
                    "'kemarin'->kemarin, 'minggu ini'->minggu_ini, "
                    "'bulan ini'->bulan_ini, 'total/semua/keseluruhan'->semua. "
                    "Jika tidak disebut, kembalikan null (dianggap hari_ini)."
                ),
            },
            "tanggal": {
                "type": ["string", "null"],
                "description": (
                    "Tanggal SPESIFIK YYYY-MM-DD bila merujuk satu hari tertentu "
                    "('senin kemarin', 'tanggal 1 juli') — hitung dari HARI INI. "
                    "null bila tidak."
                ),
            },
        },
        "required": ["is_laporan_gabah"],
    },
}


# Tool transfer internal Gudang 1 -> Gudang 2 (PK siap transfer).
PROSES_TRANSFER = {
    "name": "proses_transfer",
    "description": (
        "Deteksi & ekstrak perintah/pertanyaan TRANSFER PK dari Gudang 1 ke "
        "Gudang 2. PK yang ditandai 'siap transfer' saat milling dikirim ke "
        "Gudang 2 oleh staff/admin. Aksi: buat transfer (kirim PK ke Gudang 2), "
        "tanya PK yang siap transfer, atau tanya riwayat transfer. "
        "PENTING — pilih 'bukan_transfer' bila pesan sebenarnya BUKAN soal "
        "kirim/transfer PK antar gudang, mis.: menanyakan KODE batch/lot ('apa "
        "saja kode batchnya', 'kodenya apa'), JUMLAH batch/gabah, verifikasi, "
        "stok, atau status. Kata 'transfer'/'kirim ke gudang 2'/'PK siap "
        "transfer' harus benar-benar ada; kalau tidak, 'bukan_transfer'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": [
                    "buat_transfer",
                    "laporan_siap_transfer",
                    "laporan_transfer",
                    "bukan_transfer",
                ],
                "description": (
                    "'buat_transfer': kirim PK siap-transfer ke Gudang 2 "
                    "(contoh: 'transfer PK dari MIL-... ke silo A', 'kirim PK "
                    "siap transfer ke tumpukan gudang 2', 'transfer ke silo B'). "
                    "'laporan_siap_transfer': tanya PK yang menunggu transfer "
                    "(contoh: 'ada PK siap transfer?', 'PK siap dikirim berapa'). "
                    "'laporan_transfer': riwayat transfer (contoh: 'transfer hari "
                    "ini', 'sudah transfer apa saja'). 'bukan_transfer': lainnya."
                ),
            },
            "kode_proses": {
                "type": ["string", "null"],
                "description": "Kode proses milling sumber, MIL-YYYYMMDD-NN (huruf besar).",
            },
            "lokasi_tujuan": {
                "type": ["string", "null"],
                "enum": ["silo_a", "silo_b", "ditumpuk", None],
                "description": (
                    "Tujuan di Gudang 2: 'silo A'->silo_a, 'silo B'->silo_b, "
                    "'tumpuk/ditumpuk/tumpukan'->ditumpuk."
                ),
            },
        },
        "required": ["intent"],
    },
}


# Tool milling sisi staff/admin (Bot Admin): QC & verifikasi output PK.
PROSES_MILLING_ADMIN = {
    "name": "proses_milling_admin",
    "description": (
        "Deteksi & ekstrak aksi staff/admin untuk proses milling: input QC "
        "hasil PK, atau verifikasi berat output PK final. Contoh QC: 'QC "
        "MIL-... kadar air 13 broken 5 susut 2 kondisi KS'. Contoh verifikasi: "
        "'verifikasi output MIL-... 14 ton', 'output PK MIL-... final 14000'. "
        "Jika bukan tentang milling (mis. verifikasi HARGA gabah batch GB-...), "
        "pilih 'bukan_milling_admin'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["qc_milling", "verifikasi_output", "bukan_milling_admin"],
                "description": (
                    "'qc_milling': input hasil QC PK (kadar air/broken/susut/"
                    "kondisi). 'verifikasi_output': tetapkan berat output PK "
                    "final sebuah proses MIL-. 'bukan_milling_admin': selain itu "
                    "(termasuk verifikasi harga gabah batch GB-...)."
                ),
            },
            "kode_proses": {
                "type": ["string", "null"],
                "description": "Kode proses milling MIL-YYYYMMDD-NN (huruf besar).",
            },
            "kadar_air": {
                "type": ["number", "null"],
                "description": "Kadar air PK (persen). '13%' -> 13.",
            },
            "broken_persen": {
                "type": ["number", "null"],
                "description": "Persentase broken/pecah. '5%' -> 5.",
            },
            "susut_persen": {
                "type": ["number", "null"],
                "description": "Persentase susut. '2%' -> 2.",
            },
            "kondisi": {
                "type": ["string", "null"],
                "enum": ["KS", "KL", None],
                "description": "Kondisi PK: 'KS' atau 'KL' bila disebut.",
            },
            "berat_output_kg": {
                "type": ["number", "null"],
                "description": (
                    "Untuk verifikasi_output: berat output PK final dalam KG. "
                    "'14 ton' -> 14000."
                ),
            },
        },
        "required": ["intent"],
    },
}


# Tool proses milling / pecah kulit (Bot Gudang 1).
PROSES_MILLING = {
    "name": "proses_milling",
    "description": (
        "Deteksi & ekstrak perintah/pertanyaan terkait MILLING gabah menjadi "
        "beras PK di Gudang 1. Operator menyebut proses ini bermacam-macam — "
        "semua ARTINYA SAMA: 'milling', 'pecah kulit', 'giling', 'selep', "
        "'selepan', 'husking', atau 'proses'. Aksi: mulai proses dari isi "
        "silo, catat progress berat PK, arahkan PK keluar (tumpuk/siap "
        "transfer), tandai selesai, atau tanya laporan giling & stok PK. "
        "PENTING: 'mulai proses silo A' / 'mulai proses selep silo A' / 'selep "
        "silo A' BERARTI mulai_milling memakai bahan di silo itu (BUKAN tanya "
        "status silo). Jika benar-benar bukan tentang milling, pilih "
        "'bukan_milling'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": [
                    "mulai_milling",
                    "progress_milling",
                    "routing_pk",
                    "selesai_milling",
                    "laporan_milling",
                    "stok_pk",
                    "bukan_milling",
                ],
                "description": (
                    "'mulai_milling': mulai proses milling/selep/husking/giling "
                    "memakai gabah yang ADA DI SILO (contoh: 'giling silo A', "
                    "'mulai milling silo B', 'mulai proses silo A', 'mulai "
                    "proses selep silo A', 'selep silo A', 'husking silo A', "
                    "'mulai proses husking silo A', 'proses giling silo A', "
                    "'selepan silo A'). "
                    "'progress_milling': catat berat PK kumulatif yang sudah "
                    "keluar (contoh: 'progress giling MIL-... 5 ton', 'PK MIL-... "
                    "sudah 5000 kg'). "
                    "'routing_pk': arahkan PK yang keluar (contoh: 'tumpuk 3 ton "
                    "PK dari MIL-...', 'siap transfer 2 ton dari MIL-...'). "
                    "'selesai_milling': proses milling/selep/giling/husking "
                    "SELESAI (contoh: 'MIL-... selesai giling', 'proses selep "
                    "selesai', 'selep selesai', 'giling selesai', 'milling "
                    "selesai', 'selesai giling', 'husking selesai', 'proses "
                    "giling selesai'). Kode proses boleh tidak disebut. "
                    "'laporan_milling': status/laporan giling yang SEDANG "
                    "berjalan (contoh: 'giling apa yang jalan', 'status giling', "
                    "'laporan milling'). Pertanyaan DETAIL sebuah proses tertentu "
                    "atau proses TERAKHIR — mis. asal bahan/supplier ('proses pk "
                    "terakhir dari bahan siapa', 'giling terakhir gabahnya dari "
                    "siapa'), rendemen/hasil MIL-... — BUKAN laporan_milling, "
                    "pilih 'bukan_milling' (ditangani modul detail). "
                    "'stok_pk': tanya stok PK buffer Gudang 1. "
                    "'bukan_milling': selain itu."
                ),
            },
            "nama_silo": {
                "type": ["string", "null"],
                "enum": ["A", "B", None],
                "description": "Silo sumber untuk mulai_milling: 'A' atau 'B'.",
            },
            "kode_proses": {
                "type": ["string", "null"],
                "description": "Kode proses milling MIL-YYYYMMDD-NN (huruf besar).",
            },
            "berat_kg": {
                "type": ["number", "null"],
                "description": (
                    "Berat dalam KILOGRAM. Untuk progress_milling = berat "
                    "kumulatif total PK. Untuk routing_pk = berat yang "
                    "diarahkan. Konversi ton: '5 ton'->5000."
                ),
            },
            "tujuan": {
                "type": ["string", "null"],
                "enum": ["tumpuk", "siap_transfer", None],
                "description": (
                    "Untuk routing_pk: 'tumpuk' (simpan di buffer) atau "
                    "'siap_transfer' (siap dikirim ke Gudang 2)."
                ),
            },
        },
        "required": ["intent"],
    },
}


# Tool proses silo Gudang 1 (gabah kering).
PROSES_SILO = {
    "name": "proses_silo",
    "description": (
        "Deteksi & ekstrak perintah/pertanyaan terkait SILO gabah kering di "
        "Gudang 1 (Silo A / Silo B) — tempat PENYIMPANAN gabah yang SUDAH "
        "kering. Tiga aksi silo: memasukkan gabah ke silo, mengeluarkan/"
        "mengosongkan silo, atau menanyakan isi/status/kapasitas silo. "
        "PENTING — pilih 'bukan_silo' bila pesan sebenarnya tentang: "
        "(a) pengeringan ('oven', 'dryer', 'mesin pengering'); ATAU "
        "(b) MEMULAI PROSES/MILLING dari isi silo — mis. 'mulai proses silo A', "
        "'mulai proses selep silo A', 'selep silo A', 'giling silo A', "
        "'husking silo A', 'proses silo A' (ini perintah milling, bukan silo); "
        "ATAU (c) STOK/HASIL PK — mis. 'stok pk', 'berapa stok pk', 'stok beras "
        "pk', 'pk yang ditumpuk' (ini soal buffer PK hasil giling, bukan silo); "
        "ATAU (d) pertanyaan asal/detail gabah/lot/proses yang TIDAK menyebut "
        "kata 'silo' sama sekali — mis. 'gabah terakhir dari siapa', 'proses "
        "terakhir bahan dari siapa' (→ bukan_silo). ATURAN KUNCI: jika pesan "
        "menyebut 'silo' / 'silo A' / 'silo B', pertanyaan tentang isi/asal/"
        "pemilik/status silo SELALU 'laporan_silo' — TERMASUK 'bahan di silo A "
        "punya siapa', 'isi silo B dari siapa', 'silo A punya siapa'. Exclusion "
        "(d) hanya berlaku bila kata 'silo' TIDAK ada. Silo hanya soal simpan/"
        "keluarkan/status GABAH di silo, bukan memproses isinya dan bukan stok PK."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": [
                    "masuk_silo",
                    "pindah_mulai",
                    "pindah_selesai",
                    "keluar_silo",
                    "laporan_silo",
                    "bukan_silo",
                ],
                "description": (
                    "'masuk_silo': perintah langsung memasukkan gabah ke silo "
                    "(contoh: 'masukkan LOT-... ke silo A', 'gabah GB-... masuk "
                    "silo B langsung'). "
                    "'pindah_mulai': MEMBERITAHU proses pemindahan gabah dari "
                    "dryer ke silo DIMULAI/sedang berlangsung — gabah BELUM di "
                    "silo (contoh: 'mulai pindah ke silo A', 'sedang "
                    "memindahkan ke silo B', 'proses pindah ke silo A dimulai'). "
                    "'pindah_selesai': MEMBERITAHU pemindahan ke silo SELESAI — "
                    "gabah kini sudah di silo (contoh: 'pemindahan ke silo A "
                    "selesai', 'sudah dipindah ke silo A', 'selesai pindah ke "
                    "silo B', 'gabah sudah masuk silo A'). "
                    "'keluar_silo': kosongkan silo (contoh: 'kosongkan silo A'). "
                    "'laporan_silo': status / isi / KAPASITAS silo, khusus GABAH "
                    "(contoh: 'silo apa yang terisi', 'isi silo A apa', "
                    "'kapasitas silo berapa', 'kapasitas maksimal silo', 'silo "
                    "muat berapa ton'). JANGAN pakai laporan_silo untuk stok PK "
                    "hasil giling — itu 'bukan_silo'. 'bukan_silo': selain itu."
                ),
            },
            "nama_silo": {
                "type": ["string", "null"],
                "enum": ["A", "B", None],
                "description": "Silo yang dimaksud: 'A' atau 'B'. 'silo a' -> 'A'.",
            },
            "kode_lot": {
                "type": ["string", "null"],
                "description": (
                    "Kode lot pengeringan (LOT-YYYYMMDD-NN) bila gabah masuk "
                    "silo BERASAL dari lot pengeringan. Huruf besar."
                ),
            },
            "kode_batch": {
                "type": ["string", "null"],
                "description": (
                    "Kode batch gabah (GB-YYYYMMDD-NN) bila gabah KERING masuk "
                    "silo LANGSUNG tanpa pengeringan. Huruf besar."
                ),
            },
        },
        "required": ["intent"],
    },
}


# Tool telusur detail data (semua bot) — jawab atribut sebuah entitas.
TANYA_DETAIL = {
    "name": "tanya_detail",
    "description": (
        "Deteksi bila pengguna menanyakan ATRIBUT/DETAIL sebuah entitas tertentu "
        "(bukan sekadar kodenya, dan bukan total agregat). Contoh yang HARUS "
        "true: 'berapa harga gabah yang pertama masuk hari ini', 'berat gabah "
        "dari budi berapa', 'kadar air lot terbaru berapa', 'status GB-... "
        "gimana', 'gabah kedua sudah diverifikasi belum', 'rendemen MIL-... "
        "berapa', 'gabah pertama dari siapa', 'proses pk/giling terakhir dari "
        "bahan/supplier siapa saja', 'milling terakhir gabahnya dari siapa' "
        "(target=milling, terbaru=true). Entitas dirujuk lewat supplier, hari, "
        "urutan (pertama/kedua), kondisi, 'terbaru/terakhir', atau kode langsung."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_detail": {
                "type": "boolean",
                "description": (
                    "true jika menanyakan atribut/detail satu entitas tertentu "
                    "(harga, berat, kadar air, status, rendemen, supplier, "
                    "kapan, sudah diverifikasi belum). false untuk minta KODE "
                    "saja, total agregat, atau perintah aksi."
                ),
            },
            "target": {
                "type": ["string", "null"],
                "enum": ["batch", "lot", "milling", None],
                "description": (
                    "Jenis entitas: 'batch' (gabah GB-), 'lot' (pengeringan "
                    "LOT-), 'milling' (giling MIL-). PENTING: kata 'PK' / 'pecah "
                    "kulit' / 'proses PK' / 'hasil giling' / 'selep' -> "
                    "target='milling' (PK adalah OUTPUT milling, bukan lot "
                    "pengeringan). null -> anggap batch."
                ),
            },
            "kode": {
                "type": ["string", "null"],
                "description": "Kode langsung bila disebut (GB-/LOT-/MIL-...), huruf besar.",
            },
            "supplier_nama": {
                "type": ["string", "null"],
                "description": "Nama supplier bila disebut, mis. 'Pak Budi' -> 'Budi'.",
            },
            "periode": {
                "type": ["string", "null"],
                "enum": ["hari_ini", "kemarin", "minggu_ini", "bulan_ini", "semua", None],
                "description": "Rentang waktu bila disebut.",
            },
            "urutan": {
                "type": ["integer", "null"],
                "description": "Urutan 1-based bila disebut. 'pertama'->1, 'kedua'->2.",
            },
            "kondisi": {
                "type": ["string", "null"],
                "enum": ["basah", "kering", None],
                "description": "Kondisi gabah bila disebut (target batch).",
            },
            "terbaru": {
                "type": "boolean",
                "description": "true bila minta yang TERBARU/TERAKHIR.",
            },
            "tanggal": {
                "type": ["string", "null"],
                "description": (
                    "Tanggal SPESIFIK YYYY-MM-DD bila entitas dirujuk pada satu "
                    "hari tertentu ('gabah senin kemarin', 'batch tanggal 1 "
                    "juli') — hitung dari HARI INI. null bila tidak."
                ),
            },
        },
        "required": ["is_detail"],
    },
}


# Tool tanya status umum "apa yang sedang berlangsung" (semua bot).
TANYA_STATUS = {
    "name": "tanya_status",
    "description": (
        "Deteksi bila pengguna menanyakan secara UMUM apa yang sedang "
        "berlangsung / status kegiatan sekarang di gudang — mencakup "
        "pengeringan, pendinginan, dan milling/giling/selep sekaligus. Contoh "
        "yang HARUS true: 'proses apa yang sedang berlangsung', 'lagi proses "
        "apa', 'ada kegiatan apa sekarang', 'status gudang 1 sekarang', "
        "'sedang ngerjain apa', 'apa yang sedang jalan'. Bukan pertanyaan "
        "spesifik satu proses tertentu. PENTING: pertanyaan tentang "
        "VERIFIKASI / hal yang belum di-acc / tugas tertunda / yang perlu "
        "dikerjakan (mis. 'apa ada yang perlu diverifikasi', 'ada yang belum "
        "beres') BUKAN status → is_status=false (itu ditangani modul pending)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_status": {
                "type": "boolean",
                "description": (
                    "true HANYA jika menanyakan KEGIATAN/PROSES yang sedang "
                    "AKTIF berlangsung sekarang ('lagi proses apa', 'ada "
                    "kegiatan apa', 'sedang giling/mengeringkan apa'). "
                    "false untuk pertanyaan JUMLAH/TOTAL ('berapa gabah masuk "
                    "hari ini'), harga, stok, kode, atau laporan angka lainnya."
                ),
            }
        },
        "required": ["is_status"],
    },
}


# Tool tanya pending / tugas verifikasi (semua bot).
TANYA_PENDING = {
    "name": "tanya_pending",
    "description": (
        "Deteksi bila pengguna BERTANYA tentang apa saja yang masih perlu "
        "diverifikasi / di-acc / dikerjakan / tertunda / belum beres. Contoh "
        "yang HARUS true: 'ada yang perlu diverifikasi?', 'apa saja yang belum "
        "diverifikasi', 'ada tugas verifikasi?', 'masih ada yang belum di acc?', "
        "'ada yang menunggu verifikasi', 'yang belum beres apa'. Bedakan dari "
        "PERINTAH memverifikasi sesuatu (itu bukan pertanyaan)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_pending": {
                "type": "boolean",
                "description": (
                    "true jika pengguna menanyakan daftar hal yang masih perlu "
                    "diverifikasi/dikerjakan/tertunda. false untuk perintah aksi "
                    "atau pertanyaan lain."
                ),
            }
        },
        "required": ["is_pending"],
    },
}


# Tool cari kode batch/lot (kedua bot) — bantu pengguna yang tak hafal kode.
CARI_KODE = {
    "name": "cari_kode",
    "description": (
        "Deteksi bila pengguna BERTANYA/MENCARI kode batch gabah atau kode lot "
        "pengeringan berdasarkan ciri (dari supplier siapa, hari apa, urutan ke "
        "berapa, kondisi, atau yang terbaru) — karena mereka tidak hafal "
        "kodenya. Contoh yang HARUS true: 'batch dari pak budi kodenya apa', "
        "'kode gabah yang masuk pertama hari ini', 'gabah dari catur kemarin "
        "kode berapa', 'kode lot terbaru', 'lot yang isinya gabah budi apa "
        "kodenya', 'gabah kering hari ini kodenya'. JUGA true untuk permintaan "
        "MENYEBUT SEMUA kode (jamak), termasuk bentuk singkat/lanjutan: 'apa "
        "saja kode batchnya', 'kode batchnya apa saja', 'sebutkan kode-kode "
        "batch', 'kodenya apa saja' (bila konteksnya batch/lot). Bila hanya "
        "menyebut 'batch' -> target=batch; 'lot' -> target=lot. "
        "Bedakan dari pertanyaan JUMLAH/total (itu laporan, bukan cari kode)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_cari_kode": {
                "type": "boolean",
                "description": (
                    "true jika pengguna ingin MENGETAHUI kode (identitas) sebuah "
                    "batch/lot berdasarkan ciri. false untuk pertanyaan jumlah/"
                    "total, perintah pencatatan, atau hal lain."
                ),
            },
            "target": {
                "type": ["string", "null"],
                "enum": ["batch", "lot", None],
                "description": (
                    "'batch' jika mencari kode batch gabah (GB-...), 'lot' jika "
                    "mencari kode lot pengeringan (LOT-...). null jika tak jelas "
                    "(anggap batch)."
                ),
            },
            "supplier_nama": {
                "type": ["string", "null"],
                "description": "Nama supplier bila disebut, mis. 'Pak Budi' -> 'Budi'.",
            },
            "periode": {
                "type": ["string", "null"],
                "enum": ["hari_ini", "kemarin", "minggu_ini", "bulan_ini", "semua", None],
                "description": "Rentang waktu bila disebut ('hari ini','kemarin',...).",
            },
            "urutan": {
                "type": ["integer", "null"],
                "description": (
                    "Urutan 1-based bila disebut. 'pertama'->1, 'kedua'->2, "
                    "'ketiga'->3, 'terakhir'-> kosongkan & set terbaru=true."
                ),
            },
            "kondisi": {
                "type": ["string", "null"],
                "enum": ["basah", "kering", None],
                "description": "Kondisi gabah bila disebut (untuk target batch).",
            },
            "terbaru": {
                "type": "boolean",
                "description": "true bila pengguna minta yang TERBARU/TERAKHIR/BARUSAN.",
            },
            "tanggal": {
                "type": ["string", "null"],
                "description": (
                    "Tanggal SPESIFIK YYYY-MM-DD bila merujuk satu hari tertentu "
                    "('senin kemarin', 'tanggal 1 juli') — hitung dari HARI INI. "
                    "null bila tidak."
                ),
            },
        },
        "required": ["is_cari_kode"],
    },
}


# Tool proses pengeringan (Bot Gudang 1) — satu tool, banyak intent.
PROSES_PENGERINGAN = {
    "name": "proses_pengeringan",
    "description": (
        "Deteksi & ekstrak perintah/pertanyaan terkait PENGERINGAN gabah di "
        "Gudang 1. Pengeringan dilakukan di MESIN PENGERING — pengguna "
        "menyebutnya bermacam-macam: 'oven', 'dryer', 'mesin pengering', "
        "'pengering', atau 'dikeringkan'; semua ini berarti proses pengeringan "
        "(BUKAN silo). Empat aksi: membentuk lot pengeringan dari beberapa "
        "batch (memasukkan gabah ke oven/dryer), mencatat log kadar air, "
        "menandai pengeringan selesai (mengeluarkan dari oven/dryer), atau "
        "bertanya laporan pengeringan. PENTING: kata 'selep', 'giling', "
        "'milling', 'husking', 'pecah kulit' adalah proses MILLING (bukan "
        "pengeringan) — mis. 'selep selesai' / 'giling selesai' -> "
        "'bukan_pengeringan'. JUGA 'bukan_pengeringan' untuk pertanyaan tentang "
        "PK / hasil giling / 'proses PK' / 'stok PK' / asal-bahan sebuah milling "
        "('proses pk terakhir dari bahan siapa', 'giling terakhir gabahnya dari "
        "supplier siapa'). Jika pesan bukan tentang pengeringan (pembelian, "
        "milling, atau laporan pembelian), pilih 'bukan_pengeringan'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": [
                    "bentuk_lot",
                    "log_kadar_air",
                    "log_pendinginan",
                    "selesai_pengeringan",
                    "laporan_pengeringan",
                    "bukan_pengeringan",
                ],
                "description": (
                    "'bentuk_lot': gabungkan batch gabah jadi 1 lot untuk "
                    "dikeringkan / dimasukkan ke mesin pengering (contoh: "
                    "'keringkan GB-... dan GB-...', 'buat lot pengeringan dari "
                    "GB-...', 'masukkan gabah pertama dan kedua ke oven', "
                    "'oven-kan GB-...', 'gabah GB-... masuk dryer', 'keringkan "
                    "di mesin pengering'). "
                    "'log_kadar_air': catat/laporkan kadar air gabah yang sedang "
                    "dikeringkan — SELALU pilih ini bila ada angka kadar air, "
                    "MESKIPUN kode lot tidak disebut (kode diisi dari konteks). "
                    "Contoh: 'kadar air LOT-... 18%', 'kadar air gabah saat ini "
                    "26%', 'kadar airnya 26 persen sekarang', 'update kadar air "
                    "indikator 18 tes manual 17'. "
                    "'log_pendinginan': catat proses PENDINGINAN — setelah "
                    "pengeringan selesai, gabah tetap di dalam dryer dan hanya "
                    "kena sirkulasi udara (bukan udara panas); tidak ada "
                    "perpindahan/progress. Contoh: 'pendinginan LOT-...', "
                    "'gabah didinginkan', 'mulai pendinginan', 'proses "
                    "pendinginan', 'sirkulasi udara dingin LOT-...'. "
                    "'selesai_pengeringan': tandai lot selesai DIKERINGKAN "
                    "(fase pengeringan/pemanasan berakhir; berbeda dari "
                    "pendinginan). Contoh: 'pengeringan LOT-... selesai', "
                    "'gabah sudah kering', 'pemanasan selesai'. "
                    "'laporan_pengeringan': pertanyaan status/laporan (contoh: "
                    "'lot pengeringan apa yang jalan', 'kadar air LOT-... "
                    "berapa'). "
                    "'bukan_pengeringan': selain itu."
                ),
            },
            "kode_batch_list": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": (
                    "Untuk bentuk_lot: daftar kode batch gabah eksplisit, format "
                    "GB-YYYYMMDD-NN (huruf besar, tambahkan tanda '-'). "
                    "Contoh 'gb 20260702 01' -> 'GB-20260702-01'."
                ),
            },
            "batch_urutan_list": {
                "type": ["array", "null"],
                "items": {"type": "integer"},
                "description": (
                    "Untuk bentuk_lot bila pengguna merujuk batch dengan URUTAN, "
                    "bukan kode. Angka 1-based urutan batch pembelian HARI INI. "
                    "'pertama'->1, 'kedua'->2, 'ketiga'->3, 'keempat'->4, "
                    "'batch 1'->1, 'gabah ke-3'->3. Contoh 'keringkan gabah "
                    "pertama dan ketiga' -> [1, 3]. "
                    "PENTING beda posisi kata: 'batch KEDUA'/'gabah kedua' (kata "
                    "urut SETELAH kata batch) = urutan [2]; TAPI 'KEDUA batch'/"
                    "'kedua-duanya'/'dua-duanya'/'semua batch' (bermakna SEMUA) "
                    "BUKAN urutan — kosongkan ini dan pakai 'semua_batch'=true. "
                    "Kosongkan (null) bila pakai kode GB-... atau semua_batch."
                ),
            },
            "semua_batch": {
                "type": "boolean",
                "description": (
                    "true bila pengguna bermaksud SEMUA batch (yang belum "
                    "dilot) hari ini jadi satu lot — dipicu frasa seperti 'kedua "
                    "batch', 'kedua-duanya', 'dua-duanya', 'ketiga batch', "
                    "'semua batch', 'semua gabah hari ini'. Berbeda dari 'batch "
                    "kedua' (itu urutan ke-2, semua_batch=false)."
                ),
            },
            "kode_lot": {
                "type": ["string", "null"],
                "description": (
                    "Kode lot pengeringan, format LOT-YYYYMMDD-NN (huruf besar). "
                    "Untuk log_kadar_air / selesai_pengeringan / "
                    "laporan_pengeringan satu lot."
                ),
            },
            "kadar_air_indikator": {
                "type": ["number", "null"],
                "description": (
                    "Kadar air dari alat indikator (persen). '18%' -> 18. Bila "
                    "hanya satu angka kadar air disebut, isikan ke sini."
                ),
            },
            "kadar_air_tes_manual": {
                "type": ["number", "null"],
                "description": "Kadar air hasil tes manual (persen), bila disebut.",
            },
            "periode": {
                "type": ["string", "null"],
                "enum": ["hari_ini", "kemarin", "minggu_ini", "bulan_ini", "semua", None],
                "description": "Periode untuk laporan_pengeringan bila disebut.",
            },
            "catatan": {
                "type": ["string", "null"],
                "description": (
                    "Catatan bebas untuk log_pendinginan bila ada (mis. durasi "
                    "'sirkulasi 2 jam'). Selain itu null."
                ),
            },
        },
        "required": ["intent"],
    },
}


# Tool verifikasi harga gabah (Bot Admin — staff/admin).
VERIFIKASI_HARGA_GABAH = {
    "name": "verifikasi_harga_gabah",
    "description": (
        "Ekstrak data verifikasi/penetapan harga pembelian gabah dari pesan "
        "staff/admin. Batch bisa dirujuk lewat KODE (GB-...) ATAU secara "
        "deskriptif (urutan 'pertama/kedua', supplier 'dari catur', 'yang "
        "terakhir/terbaru'). Contoh: 'verifikasi GB-20260702-01 total 42 juta', "
        "'gabah yang datang pertama harganya 7500 per kg', 'gabah dari catur "
        "8.000 per kg'. Jika sebuah data tidak disebut, kembalikan null."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_verifikasi_harga": {
                "type": "boolean",
                "description": (
                    "true jika pesan MENYATAKAN / MENETAPKAN / MENYETUJUI harga "
                    "atau biaya sebuah batch gabah — dikenali dari adanya SEBUAH "
                    "NILAI HARGA yang dinyatakan untuk sebuah batch (dirujuk lewat "
                    "kode GB-... ATAU deskriptif: 'pertama', 'dari catur', "
                    "'terakhir'), TANPA harus ada kata 'verifikasi'. Deteksi dari "
                    "MAKNA. Contoh yang HARUS true: 'verifikasi GB-... 42jt', "
                    "'GB-... 5rb per kilo', 'gabah yang datang pertama harganya "
                    "7500 per kg', 'gabah dari catur 8.000/kg', 'batch kedua total "
                    "42 juta', 'yang terakhir 5.250 sekilo'. "
                    "false untuk PERTANYAAN (bukan penetapan): 'berapa harga gabah "
                    "pertama', 'apa yang perlu diverifikasi', 'gabah mana yang "
                    "belum diverifikasi' — ini bukan penetapan harga. Juga false "
                    "untuk stok/laporan/sapaan."
                ),
            },
            "kode_batch": {
                "type": ["string", "null"],
                "description": (
                    "Kode batch gabah yang diverifikasi, format GB-YYYYMMDD-NN. "
                    "Normalkan ke huruf besar. Contoh: 'gb 20260702 01' -> "
                    "'GB-20260702-01'. null bila batch dirujuk deskriptif."
                ),
            },
            "urutan": {
                "type": ["integer", "null"],
                "description": (
                    "Urutan batch (1-based) bila dirujuk begitu: 'pertama'->1, "
                    "'kedua'->2, 'ketiga'->3. null bila tidak."
                ),
            },
            "supplier_nama": {
                "type": ["string", "null"],
                "description": "Nama supplier bila batch dirujuk begitu ('dari catur'->'catur').",
            },
            "terbaru": {
                "type": "boolean",
                "description": "true bila batch dirujuk sebagai yang TERAKHIR/TERBARU.",
            },
            "metode_harga": {
                "type": ["string", "null"],
                "enum": ["total", "per_kg", None],
                "description": (
                    "'total' bila nilai adalah TOTAL biaya seluruh batch "
                    "(kata kunci: total, semua). 'per_kg' bila nilai adalah "
                    "harga PER KILOGRAM (kata kunci: per kg, /kg, perkilo). "
                    "Jika tidak jelas, kembalikan null."
                ),
            },
            "nilai_rupiah": {
                "type": ["number", "null"],
                "description": (
                    "Nilai uang dalam RUPIAH (angka bulat). Konversi satuan "
                    "Indonesia: '42 juta'/'42jt' -> 42000000; '5 ribu' -> 5000; "
                    "'5.250' (titik = pemisah ribuan) -> 5250; "
                    "'Rp 5.250' -> 5250."
                ),
            },
        },
        "required": ["is_verifikasi_harga"],
    },
}


# Tool tanya pola/analitik jam kedatangan gabah (insight).
TANYA_JAM = {
    "name": "tanya_jam_kedatangan",
    "description": (
        "Deteksi bila pengguna menanyakan POLA / ANALISA / KEBIASAAN JAM "
        "kedatangan gabah (agregat banyak batch), bukan satu batch tertentu. "
        "Contoh yang HARUS true: 'jam berapa biasanya gabah masuk', 'pola jam "
        "kedatangan gabah', 'analisa jam gabah datang', 'rata-rata gabah masuk "
        "jam berapa', 'gabah paling sering datang jam berapa', 'biasanya catur "
        "kirim jam berapa'. "
        "FALSE untuk: satu batch spesifik ('kapan gabah dari catur pertama "
        "sampai', 'jam berapa gabah pertama datang' — itu detail satu batch); "
        "JUMLAH/berapa banyak ('berapa gabah masuk hari ini' — itu laporan); "
        "kode; harga; stok."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_tanya_jam": {
                "type": "boolean",
                "description": (
                    "true hanya jika menanyakan POLA/ANALISA/rata-rata/kebiasaan "
                    "JAM kedatangan gabah lintas banyak batch."
                ),
            },
            "supplier_nama": {
                "type": ["string", "null"],
                "description": "Nama supplier bila difilter ('catur'). null bila semua.",
            },
            "periode": {
                "type": ["string", "null"],
                "enum": ["hari_ini", "kemarin", "minggu_ini", "bulan_ini", "semua", None],
                "description": (
                    "Rentang waktu bila disebut. null -> keseluruhan (pola "
                    "paling bermakna dari seluruh riwayat)."
                ),
            },
            "tanggal": {
                "type": ["string", "null"],
                "description": (
                    "Tanggal SPESIFIK format YYYY-MM-DD bila pengguna merujuk "
                    "satu hari tertentu ('senin kemarin', 'tanggal 1 juli') — "
                    "hitung dari konteks HARI INI. null bila tidak."
                ),
            },
        },
        "required": ["is_tanya_jam"],
    },
}


# Tool manajemen pengguna (Bot Admin): daftar/list/aktifkan/nonaktifkan user.
KELOLA_USER = {
    "name": "kelola_user",
    "description": (
        "Deteksi & ekstrak perintah admin untuk MENGELOLA PENGGUNA sistem: "
        "mendaftarkan pengguna baru, melihat daftar pengguna, mengaktifkan, "
        "atau menonaktifkan. Contoh: 'daftarkan operator Budi id 12345678 "
        "gudang 1', 'tambah staff Sari hp 081234567890', 'daftar user', "
        "'nonaktifkan Budi', 'aktifkan Sari'. Jika bukan tentang pengelolaan "
        "pengguna, pilih intent 'bukan_user'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": [
                    "daftar_user",
                    "list_user",
                    "aktifkan_user",
                    "nonaktifkan_user",
                    "bukan_user",
                ],
                "description": (
                    "'daftar_user': daftarkan pengguna BARU (ada nama + peran + "
                    "id/hp). 'list_user': tampilkan semua pengguna ('daftar "
                    "user', 'siapa saja usernya'). 'aktifkan_user' / "
                    "'nonaktifkan_user': ubah status pengguna yang sudah ada. "
                    "'bukan_user': selain itu."
                ),
            },
            "nama": {
                "type": ["string", "null"],
                "description": "Nama pengguna. Contoh: 'Budi'.",
            },
            "role": {
                "type": ["string", "null"],
                "enum": ["operator", "staff", "admin", None],
                "description": "Peran pengguna bila disebut.",
            },
            "gudang": {
                "type": ["integer", "null"],
                "enum": [1, 2, None],
                "description": "Nomor gudang untuk operator: 1 (Selepan) atau 2 (Penyosohan).",
            },
            "telegram_id": {
                "type": ["integer", "null"],
                "description": "Telegram ID (angka) bila disebut ('id 12345678').",
            },
            "no_hp": {
                "type": ["string", "null"],
                "description": "Nomor HP bila disebut ('hp 081234567890', '0812...').",
            },
            "ref": {
                "type": ["string", "null"],
                "description": (
                    "Untuk aktifkan/nonaktifkan: rujukan pengguna (nama atau ID)."
                ),
            },
        },
        "required": ["intent"],
    },
}


# Tool undo tindakan terakhir (operator: milik sendiri; admin: bisa per orang).
UNDO_TERAKHIR = {
    "name": "undo_terakhir",
    "description": (
        "Deteksi permintaan MEMBATALKAN/UNDO tindakan/input TERAKHIR. Contoh: "
        "'undo', 'batalkan tindakan terakhir', 'batalkan input terakhir', "
        "'undo lot terakhir', 'salah, batalkan tadi', 'undo input terakhir "
        "operator gudang 1', 'batalkan input terakhir si budi'. Jika bukan "
        "permintaan undo, is_undo=false."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_undo": {
                "type": "boolean",
                "description": "true bila pengguna minta membatalkan tindakan terakhir.",
            },
            "scope": {
                "type": ["string", "null"],
                "enum": [
                    "saya",
                    "operator_gudang1",
                    "operator_gudang2",
                    "staff",
                    "semua",
                    None,
                ],
                "description": (
                    "Cakupan 'oleh siapa' (khusus admin). 'operator gudang 1'->"
                    "operator_gudang1, 'operator gudang 2'->operator_gudang2, "
                    "'staff'->staff, 'semua/siapa saja'->semua. null / 'punya "
                    "saya' -> saya."
                ),
            },
            "nama": {
                "type": ["string", "null"],
                "description": "Nama orang spesifik bila disebut ('si budi'->'budi').",
            },
        },
        "required": ["is_undo"],
    },
}


# Tool analitik strategis (Bot Admin): scorecard supplier & tren HPP.
TANYA_ANALITIK = {
    "name": "tanya_analitik",
    "description": (
        "Deteksi pertanyaan ANALITIK STRATEGIS. Contoh: 'supplier mana paling "
        "menguntungkan', 'scorecard supplier', 'peringkat pemasok', 'tren HPP', "
        "'biaya produksi PK per bulan', 'rincian biaya produksi MIL-...', "
        "'HPP MIL-... berapa'. Bila bukan analitik strategis, 'bukan_analitik'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": [
                    "supplier_scorecard",
                    "hpp_tren",
                    "rincian_biaya",
                    "bukan_analitik",
                ],
                "description": (
                    "'supplier_scorecard': peringkat/analisa supplier "
                    "(untung/harga/rendemen/kualitas). 'hpp_tren': tren biaya "
                    "pokok PK per kg dari waktu ke waktu. 'rincian_biaya': "
                    "rincian biaya produksi & HPP satu proses giling (mis. "
                    "'rincian biaya MIL-...', 'hpp MIL-... berapa', 'biaya "
                    "produksi giling terakhir'). 'bukan_analitik': lainnya."
                ),
            },
            "kode_proses": {
                "type": ["string", "null"],
                "description": "Kode proses MIL-YYYYMMDD-NN utk rincian_biaya (huruf besar).",
            },
        },
        "required": ["intent"],
    },
}
