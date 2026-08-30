# DRAF USULAN REVISI — SISTEM TARA & PEMBELIAN BERAS PECAH KULIT (PK)

**Perihal: penyelarasan pasal refaksi kualitas dan tara bawaan dengan praktik yang berjalan**
PT Hadi Mulya Utama · disusun 25 Agustus 2026

> **Status: DRAF untuk ditinjau Direksi.** Dokumen resmi tidak diubah sebelum usulan ini disetujui.

---

## 1. Latar belakang

*Sistem Tara & Pembelian Beras Pecah Kulit (PK)* mengatur refaksi kualitas pada empat tempat. Direksi menyatakan pada 25 Agustus 2026 bahwa **refaksi kualitas tidak dipakai** dalam praktik pembelian PK.

Selisih antara dokumen dan praktik ini perlu ditutup, dengan dua alasan:

1. Dokumen ini dinyatakan pada butir 11 sebagai pedoman yang **digunakan bersama Staff Timbangan, Gudang, Purchasing, Accounting, dan Supplier**. Pasal yang tidak dijalankan membuka ruang tafsir bagi pihak luar bahwa perusahaan *boleh* melakukan potongan mutu.
2. Butir 10 menegaskan perusahaan tidak menetapkan potongan secara sepihak. Pasal refaksi yang menganggur melemahkan pesan itu, padahal pesan itulah kekuatan utama dokumen ini.

## 2. Pasal yang terdampak

| Letak | Bunyi sekarang |
|---|---|
| Butir 2 angka 5 — Prinsip Utama | "Refaksi kualitas — Jika ada refaksi kualitas, dicatat dan dihitung terpisah dari tara karung." |
| Butir 8 — Pemisahan Tara dan Refaksi Kualitas | Baris tabel: "Refaksi kualitas \| Hasil pemeriksaan mutu \| Dihitung terpisah sesuai ketentuan mutu yang disepakati" |
| Butir 9 angka 7 — Prosedur Operasional | "Jika terdapat pemeriksaan kualitas/refaksi, catat pada bagian terpisah." |
| Butir 11 — Ketentuan Penutup | "Setiap perubahan tara standar, jenis karung, atau ketentuan refaksi kualitas harus dicatat dan disetujui oleh pihak yang berwenang." |

## 3. Dua pilihan penyelesaian

| | Pendekatan | Kelebihan | Kekurangan |
|---|---|---|---|
| **A** | **Hapus** seluruh pasal refaksi | Dokumen paling bersih; tidak ada ruang tafsir sama sekali | Bila suatu saat refaksi diberlakukan, prinsip "terpisah dari tara" hilang dan harus disusun ulang dari nol |
| **B** *(usulan penyusun)* | **Pertahankan pasal, tandai tidak diberlakukan** | Pesan ke supplier justru menguat: perusahaan menyatakan tegas tidak ada potongan mutu. Prinsip pemisahan tetap terjaga bila kelak diperlukan | Dokumen sedikit lebih panjang |

Usulan **B** dipilih karena mengubah pasal yang menganggur menjadi jaminan tertulis bagi supplier — sesuatu yang menambah nilai dokumen, bukan sekadar merapikannya.

## 4. Usulan bunyi baru (pilihan B)

### Butir 2 angka 5 — Prinsip Utama

> **Sekarang:** Refaksi kualitas — Jika ada refaksi kualitas, dicatat dan dihitung terpisah dari tara karung.

> **Usulan:** **Refaksi kualitas — Perusahaan saat ini TIDAK memberlakukan refaksi kualitas pada pembelian PK. Satu-satunya pengurang berat adalah tara karung sebagaimana diatur butir 4 dan 5. Apabila di kemudian hari refaksi diberlakukan, ketentuannya wajib disepakati lebih dahulu, dicatat, dan dihitung terpisah dari tara karung.**

### Butir 8 — Pemisahan Tara dan Refaksi Kualitas

> **Sekarang:** baris tabel "Refaksi kualitas \| Hasil pemeriksaan mutu \| Dihitung terpisah sesuai ketentuan mutu yang disepakati"

> **Usulan:** baris tetap ada, kolom Perlakuan diganti menjadi **"Tidak diberlakukan saat ini. Bila kelak diberlakukan, dihitung terpisah sesuai ketentuan mutu yang disepakati dan tidak pernah dicampur ke tara karung."**

### Butir 9 angka 7 — Prosedur Operasional Staff Timbang

> **Sekarang:** Jika terdapat pemeriksaan kualitas/refaksi, catat pada bagian terpisah.

> **Usulan:** **Tidak ada potongan lain di luar tara karung. Staff timbang tidak berwenang menetapkan potongan mutu dalam bentuk apa pun.**

### Butir 10 — Pesan untuk Supplier

> **Usulan tambahan satu kalimat di akhir paragraf:** **Selain tara karung yang dihitung dari sampling aktual, perusahaan tidak menerapkan potongan lain atas berat PK yang diserahkan.**

### Butir 11 — Ketentuan Penutup

> **Sekarang:** Setiap perubahan tara standar, jenis karung, atau ketentuan refaksi kualitas harus dicatat dan disetujui oleh pihak yang berwenang.

> **Usulan:** **Setiap perubahan tara standar, jenis karung, atau pemberlakuan kembali refaksi kualitas harus dicatat dan disetujui oleh pihak yang berwenang, yaitu Direksi (Wahid).**

## 5. Dampak pada webapp timbangan

| Ketentuan baru | Cara sistem menegakkannya |
|---|---|
| Tidak ada potongan mutu | Tidak ada kolom refaksi maupun potongan di seluruh basis data — secara teknis tidak mungkin dilakukan |
| Tidak ada potongan tetap atas nama toleransi | Sama: kolomnya memang tidak dibuat |
| Satu-satunya pengurang adalah tara karung | Nota timbang hanya memuat enam angka wajib butir 9, tanpa baris potongan apa pun |
| Perubahan tara standar disetujui pihak berwenang | Tara standar baru tidak berlaku sebelum disetujui akun **Wahid** |
| Supplier berhak meminta sampling ulang | Sampling ulang beralasan "keberatan supplier" tercatat; riwayat tara lama tidak pernah dihapus |

Bila kelak refaksi diberlakukan kembali, kolom `potongan_kg` pada modul QC Gudang 2 sudah tersedia dan tinggal disambungkan — tidak perlu membangun ulang.

## 6. Usulan kedua — tara bawaan untuk pihak yang belum disampling

### Latar belakang

Butir 4 mensyaratkan tara ditetapkan dari sampling minimal 30 karung. Dalam praktik, pihak baru datang membawa muatan sebelum sempat disampling. Bila transaksi ditolak sampai sampling selesai, truk tertahan di pos tanpa manfaat.

### Usulan penambahan pada Butir 4

> **Tambahan:** **Selama tara standar seorang pihak belum ditetapkan, dipakai tara bawaan 0,1 kg per karung. Tara bawaan bersifat sementara dan wajib digantikan hasil sampling pada kesempatan pertama. Pihak yang bersangkutan diberi tahu bahwa taranya masih memakai angka bawaan.**

Dengan ini pekerjaan tidak tertahan, sementara prinsip butir 10 — tara ditentukan lewat sampling aktual, bukan potongan sepihak — tetap berlaku sebagai aturan akhir. Sistem menandai setiap transaksi yang memakai tara bawaan, sehingga daftar yang menunggu sampling selalu terlihat.

**Yang perlu diputuskan:** apakah 0,1 kg adalah angka bawaan yang tepat, dan berapa lama batas toleransi sebelum sampling wajib dilakukan.

## 7. Yang perlu diputuskan

1. Pasal refaksi: pilih pendekatan **A** (hapus) atau **B** (pertahankan dengan penandaan).
2. Tara bawaan: setujui penambahan pada Butir 4, beserta angka dan batas waktunya.
3. Konfirmasi penyebutan nama **Wahid** sebagai pihak berwenang pada butir 11 — apakah dituliskan sebagai nama, atau cukup sebagai jabatan "Direksi".
4. Setelah disetujui, dokumen resminya diperbarui dan diberi nomor revisi serta tanggal berlaku.

---

*Disetujui oleh:* ................................... *Tanggal:* ......................
