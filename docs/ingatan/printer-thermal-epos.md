---
name: printer-thermal-epos
description: Struk 80mm lewat ePOS-Print di TM-m30III; LIVE 2026-09-02; sertifikat printer cacat → cap "Not Secure" diterima Direksi
metadata:
  type: project
---

Printer struk kantor: EPSON **TM-m30III**, 192.168.1.128, nama Bonjour `EPSONB83126.local`.
Firmware 13.21 ESC/POS · TM-i 01.39 · ePOS-Print 6.30 · ePOS-Device 2.90.

**AirPrint tidak ada dan tidak bisa dinyalakan pada model ini.** Panel admin
(Advanced maupun TM-i Settings) tak punya menu AirPrint; rekaman mDNS printer
mengiklankan `pdl=application/octet-stream` tanpa `URF`, dan `Validate-Job`
untuk `application/pdf` ditolak. Antrean "EPSON TM Thermal (203dpi)" yang
terlihat mengiklankan PDF/PWG-raster itu **milik Mac NurhaniOSX** (berbagi CUPS),
bukan printernya — jangan tertukar lagi.

Jalur yang benar: **ePOS-Print** (sudah `Enable`; ePOS-Device masih `Disable`).
POST XML SOAP ke `/cgi-bin/epos/service.cgi?devid=local_printer&timeout=10000`
di port 80 **dan** 443 → `success="true"`. Uji cetak 80 mm (48 kolom) berhasil
2026-09-02. Endpoint mengirim `Access-Control-Allow-Origin: *` dan
`Access-Control-Allow-Private-Network: true`, preflight OPTIONS dijawab — jadi
memang dirancang dipanggil dari JavaScript halaman web.

**Terbangun 2026-09-02** di repo timbangan, cabang `feat/cetak-epos`
(`app/timbangan/epos.py` menyusun perintah, `bukti.py` memegang baris angka
bersama jalur PDF, halaman `/timbangan/printer` untuk penyiapan per perangkat).
Jalur yang dipilih user: **A — langsung dari HP**, bukan agen LAN.

**Jebakan yang sudah memakan satu cetakan gagal:** `dw` dan `em` di ePOS-Print
adalah SAKLAR pada alat, bukan sifat satu baris. Menyalakan `dw` untuk nama
perusahaan membuat SELURUH struk tercetak dua kali lebar — 48 kolom jadi 24,
tiap baris patah di tengah kata. Sekarang tiap baris menuliskan gaya hurufnya
penuh. Jebakan kedua: menengahkan di Python LALU memakai `align="center"`
menggeser teks ke kanan, karena spasi kita ikut terhitung isi baris.

Dua ganjalan bila dipanggil langsung dari halaman HTTPS (Railway):
1. *Mixed content* — harus `https://192.168.1.128`, dan sertifikatnya swa-tanda,
   jadi tiap perangkat perlu sekali membuka alamat itu lalu menerima peringatan.
2. Chrome 151 punya izin **local-network-access** (status `prompt`); fetch lintas
   origin menggantung sampai izin diberikan. Sekali klik per situs per perangkat.

**Sertifikat printer CACAT untuk alamatnya sendiri** — ini akar semua masalah
perangkat. Isinya: nama `EPSOND400E61` (printer ini `EPSONB83126`), menjamin
alamat 192.168.192.128 (printer ini 192.168.1.128), berlaku 2010–2038. Pabrik
memasang sertifikat yang sama di banyak unit. Tidak ada browser yang menerimanya
tanpa persetujuan manual, dan persetujuan itu melekat per perangkat — itulah
sebabnya Mac bisa (pernah masuk panel admin) sementara Android/Windows tidak.

**Akibat yang DITERIMA Direksi 2026-09-02:** menyetujui sertifikat itu membuat
Chrome memberi cap "Not Secure" pada alamat aplikasi Railway selama dipakai
mencetak. Saya menyarankan menolak jalur ini; user memilih menerimanya.
Dua jalur tanpa cap yang ditolak:
- sertifikat Let's Encrypt untuk `printer.hadimulya.com` → DNS publik menunjuk
  IP privat, tantangan DNS-01, unggah ke printer (menunya ada). Ditolak karena
  unggah ulang 4×/tahun dan berhenti total bila terlupakan.
- relai/agen di jaringan pos. Ditolak karena perlu satu perangkat selalu nyala.
  Tetap jalan keluar bila cap itu jadi masalah — sekalian pembaca BX1, lihat
  [[timbangan-module]] dan [[timbangan-intake-integrasi]].

Cap itu WAJIB tetap dijelaskan di `/timbangan/printer`; jangan dihapus.

Halaman itu juga punya **pemeriksa sambungan** yang memisahkan tiga sebab
kegagalan (izin jaringan / sertifikat / beda jaringan) — pakai itu lebih dulu
sebelum menebak, karena ketiganya terasa sama dari layar.
