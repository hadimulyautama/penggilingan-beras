# Catatan proyek — arsip ingatan

Isi folder ini adalah catatan yang dikumpulkan Claude Code selama membangun
sistem ini: riwayat keputusan, jebakan yang pernah memakan waktu berjam-jam,
dan keadaan tiap bagian pada saat catatannya ditulis.

Mulailah dari [`MEMORY.md`](MEMORY.md) — daftar isi satu baris per catatan.

## Kenapa ada di dalam repo

Ingatan Claude Code disimpan di folder pribadi pada **masing-masing
komputer**, di direktori yang namanya diturunkan dari alamat lengkap folder
proyek. Alamat di Mac dan di Windows berbeda, jadi ingatan tidak berpindah
sendiri: sesi di komputer kedua mulai dari kosong.

Menaruh salinannya di sini membuat catatan itu ikut ke mana pun repo dibawa.

Yang **otomatis** terbaca di komputer mana pun adalah `CLAUDE.md` di akar tiap
repo. Isinya sengaja pendek — hanya yang wajib diketahui sejak menit pertama.
Folder ini arsip panjangnya, dibaca saat diperlukan saja.

## Memasangnya di komputer lain

1. Klon repo, lalu buka sesi Claude Code di folder induk proyek sekali saja.
   Sesi itu yang membuatkan direktori ingatannya.
2. Cari direktori yang baru terbentuk di bawah `%USERPROFILE%\.claude\projects\`
   (Windows) atau `~/.claude/projects/` (Mac & Linux). Namanya panjang dan
   memuat alamat folder proyek Anda.
3. Salin seluruh isi folder ini ke sub-direktori `memory` di dalamnya.
   Buat `memory` bila belum ada.

Jangan menebak nama direktorinya — biarkan Claude Code membuatnya lebih dulu,
lalu salin ke yang benar-benar terbentuk.

## Kalau catatannya berselisih dengan kode

**Kodenya yang benar.** Tiap catatan menggambarkan keadaan pada saat ia
ditulis, dan sebagian sudah lewat. Yang menyebut berkas, fungsi, atau saklar
tertentu harus diperiksa dulu keberadaannya sebelum dipercaya.

Contoh yang sudah usang: catatan lama menyebut tiga bot Telegram dan sebuah
layanan `mcp`. Keduanya sudah dibubarkan.
