# Nuku Review Redirect

Satu titik kontrol untuk semua link Google Review klien Nuku Creative Studio.

QR code dan NFC tag yang tercetak/tertanam di akrilik klien **tidak pernah** encode URL
Google secara langsung — semuanya mengarah ke `https://go.nukustudio.id/r/{slug}`, dan layanan
ini yang meneruskannya ke tujuan asli. Kalau Place ID Google berubah atau rusak, cukup
update satu field di sini; produk fisik yang sudah di tangan klien tetap berfungsi.

**Urutan kerjanya: cetak dulu, aktivasi belakangan.** Kartu diproduksi massal sebagai
stok polos — slug sudah ada di sistem tapi belum terhubung ke bisnis mana pun. Saat
closing dengan klien baru, satu kartu dari stok diaktivasi lewat link privat bertoken.
Kartu fisiknya tidak pernah dicetak ulang di antara dua fase itu.

## Stack

| Bagian | Pilihan |
|---|---|
| Backend | FastAPI (Python 3.12+; lokal 3.14, VPS 3.12) |
| Database | MariaDB 10.11 + SQLAlchemy 2.x async + Alembic |
| QR | `qrcode` → output SVG (vector, aman dicetak di ukuran apa pun) |
| Auth admin | API key di header `X-Admin-Key` |
| Deployment | systemd (`go-nukustudio.service`) menjalankan `run.py` di `127.0.0.1:8000`, di depannya Nginx + Let's Encrypt |

## Struktur folder

```
.
├── app/
│   ├── main.py            # entrypoint FastAPI
│   ├── config.py          # env vars (DATABASE_URL, ADMIN_API_KEY, BASE_URL, ...)
│   ├── database.py        # async engine + session
│   ├── models.py          # ReviewLink (+ LinkStatus), RedirectHit
│   ├── schemas.py         # Pydantic + validasi slug
│   ├── crud.py            # query database + generate slug/token batch
│   ├── qr.py              # QR SVG per slug + ZIP banyak QR sekaligus
│   ├── places.py          # lookup Place ID (Places API New)
│   ├── routers/
│   │   ├── redirect.py    # GET /r/{slug}
│   │   ├── setup.py       # GET & POST /setup/{slug} — aktivasi publik bertoken
│   │   ├── panel.py       # GET /admin/panel — halaman kerja admin
│   │   └── admin.py       # /admin/*
│   └── templates/
│       ├── setup.html     # form aktivasi klien
│       └── panel.html     # panel kerja admin
├── alembic/               # migrations
├── deploy/                # salinan systemd unit + config Nginx yang dipakai VPS
├── run.py                 # entry point yang dipanggil systemd
├── api.http               # koleksi request siap pakai
├── requirements.txt       # dependency produksi
├── requirements-dev.txt   # + aiosqlite untuk dev lokal tanpa MariaDB
└── .env.example
```

## Setup lokal

> **Perhatian saat membuat venv.** Jangan jalankan `python -m venv .venv` di folder
> yang venv-nya sudah ada — venv akan mengganti interpreter tapi membiarkan paket
> lama, dan hasilnya error `No module named 'pydantic_core._pydantic_core'`. Hapus
> dulu foldernya (`rmdir /s .venv`) kalau mau bikin ulang.

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env          # Linux/macOS: cp .env.example .env
```

Isi `.env`, lalu generate admin key yang benar-benar acak:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Jalankan migrasi lalu server:

```bash
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Dokumentasi interaktif: <http://127.0.0.1:8000/admin/docs>

> **Dev tanpa MariaDB.** `.env.example` sudah default ke SQLite, dan
> `requirements-dev.txt` sudah menyertakan `aiosqlite` — jadi hasil `copy` di atas
> langsung bisa dipakai tanpa menyalakan database apa pun. Semua endpoint jalan sama
> persis seperti di MariaDB. Yang perlu diganti hanya `ADMIN_API_KEY`.

## Menjalankan tes



Menguji alur ujung-ke-ujung memakai SQLite sementara dan memanggil aplikasi
langsung lewat ASGI — tidak butuh MariaDB maupun server yang sedang berjalan,
jadi aman dijalankan kapan saja. Butuh `requirements-dev.txt`.

Jalankan ini sebelum `git push`, karena deploy di VPS menarik langsung dari
branch `main`.

## Setup database produksi

Di VPS sudah tersedia MariaDB 10.11 dengan database `nuku_redirect` dan user
`nuku_admin`. Jadi yang perlu dilakukan hanya **membersihkan tabel lama**, lalu
membiarkan Alembic membuat skemanya.

Tabel `review_links` yang dibuat manual memakai skema versi lama (`active` boolean,
belum ada `status` / `activation_token` / `batch_label`), jadi tidak cocok lagi.
Belum ada data produksi, jadi menghapusnya aman.

```bash
mysql -u nuku_admin -p nuku_redirect
```

> Saat diminta password, ketik apa adanya termasuk karakter `@`. Encoding `%40`
> **hanya** berlaku di dalam `DATABASE_URL`, bukan saat login manual.

Di prompt `MariaDB [nuku_redirect]>`:

```sql
DROP TABLE IF EXISTS redirect_hits;
DROP TABLE IF EXISTS review_links;
DROP TABLE IF EXISTS alembic_version;
```

`alembic_version` ikut dihapus supaya Alembic mulai bersih dari
`0001_card_provisioning`, bukan mencari revisi lama yang sudah tidak ada.

Keluar dengan `exit`, lalu:

```bash
cd /var/www/go.nukustudio.id && venv/bin/alembic upgrade head
```

Tanpa langkah drop di atas, perintah ini berhenti dengan
`1050 Table 'review_links' already exists`.

<details>
<summary>Lampiran: bikin database dari nol (hanya kalau server diganti)</summary>

Tidak perlu dijalankan di VPS sekarang — database dan user-nya sudah ada, dan
menjalankan ini lagi hanya menghasilkan error `database exists`.

```sql
CREATE DATABASE nuku_redirect CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'nuku_admin'@'localhost' IDENTIFIED BY 'password-yang-kuat';
GRANT ALL PRIVILEGES ON nuku_redirect.* TO 'nuku_admin'@'localhost';
FLUSH PRIVILEGES;
```

Password yang mengandung `@` harus ditulis `%40` di `DATABASE_URL`, kalau tidak
parser URL salah membaca batas antara password dan hostname.

</details>

## Endpoint

| Method & path | Fungsi | Auth |
|---|---|---|
| `GET /r/{slug}` | **URL yang tercetak di QR/NFC.** Kalau `status=active` → **302** ke `destination_url` dan hit dicatat. Kalau `unassigned`/`inactive` → halaman "kartu belum aktif". Tidak pernah membaca parameter `key` | Publik |
| `GET /setup/{slug}?key={token}` | Form aktivasi klien. Tampil hanya kalau token cocok **dan** status masih `unassigned` | Token |
| `POST /setup/{slug}` | Submit aktivasi (`business_name`, `destination_url`, `key`) → set `status=active` | Token |
| `GET /admin/panel` | **Panel kerja admin** — daftar kartu, QR, mode tulis NFC, pesan aktivasi | Login di halaman |
| `GET /health` | Health check untuk monitoring | Publik |
| `POST /admin/slugs/batch` | Generate N kartu polos + token sekaligus. `batch_label` default `batch-YYYY-MM` | `X-Admin-Key` |
| `GET /admin/qr/export` | Satu ZIP berisi semua QR SVG yang cocok `?batch_label=` atau `?status=` | `X-Admin-Key` |
| `GET /admin/links` | List semua kartu (filter `?status=` dan/atau `?batch_label=`) | `X-Admin-Key` |
| `GET /admin/links/{slug}` | Detail satu kartu, termasuk `setup_url` selama masih `unassigned` | `X-Admin-Key` |
| `PATCH /admin/links/{slug}` | Update `business_name`, `destination_url`, dan/atau `status` | `X-Admin-Key` |
| `GET /admin/links/{slug}/qr` | QR SVG satu kartu. Opsi `?compact=true` (29x29) dan `?download=false` | `X-Admin-Key` |
| `GET /admin/links/{slug}/stats` | Total hit + 7 hari terakhir + hit terakhir kapan | `X-Admin-Key` |
| `POST /admin/lookup-place` | Cari Place ID dari `business_name` + `full_address` lewat Places API | `X-Admin-Key` |

Contoh request lengkap ada di [api.http](api.http).

```bash
curl -X POST http://127.0.0.1:8000/admin/slugs/batch \
  -H "X-Admin-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"count":50}'
```

```bash
curl -H "X-Admin-Key: $ADMIN_API_KEY" \
  "http://127.0.0.1:8000/admin/qr/export?batch_label=batch-2026-09" -o qr-batch-2026-09.zip
```

## Keputusan desain yang perlu diingat

- **302, bukan 301.** Browser dan aplikasi scanner meng-cache 301 secara permanen.
  Kalau sampai ter-cache, ganti Place ID di sini tidak akan berpengaruh di HP yang
  sudah pernah scan — persis masalah yang mau dihindari layanan ini.
- **Tidak ada endpoint hard-delete.** Slug yang sudah tercetak di akrilik klien tidak
  boleh bisa hilang permanen karena salah klik. Klien berhenti → `status: inactive`.
- **`/r/{slug}` dan `/setup/{slug}` adalah dua rute yang benar-benar terpisah.** URL di
  kartu tidak pernah membawa token, dan rute redirect tidak pernah membaca parameter
  `key`. Siapa pun yang menemukan kartu fisik tidak bisa masuk ke form aktivasi, karena
  tokennya memang tidak ada di kartu.
- **Token jadi sekali pakai tanpa logika expiry.** `/setup` mensyaratkan token cocok
  **dan** status masih `unassigned`. Begitu aktivasi berhasil, status berubah dan syarat
  kedua otomatis gagal selamanya. Tidak ada tanggal kedaluwarsa yang perlu diurus.
- **Pesan gagal di `/setup` selalu sama persis** untuk token salah, slug tidak ada, dan
  kartu sudah dipakai. Membedakannya akan membantu orang menebak token yang benar.
- **ZIP hasil `qr/export` hanya berisi SVG.** Tidak ada manifest berisi token di
  dalamnya — file itu dikirim ke percetakan, dan token tidak boleh ikut ke sana.
- **Aktivasi lewat admin butuh `destination_url`.** `PATCH` dengan `status=active` pada
  kartu yang belum punya tujuan ditolak `400`, supaya tidak ada kartu "aktif" yang
  meredirect ke tempat kosong.
- **Slug tidak bisa diubah lewat PATCH**, alasan yang sama: slug adalah barang fisik.
- **Slug divalidasi URL-safe**: huruf kecil, angka, dan strip di antaranya, 3–64
  karakter. Input di-lowercase otomatis, dan duplikat ditolak `409`.
- **Kartu mati tidak menampilkan 404 mentah** — yang scan mendapat halaman
  "Kartu belum aktif" (HTTP 200) dengan tombol WhatsApp langsung ke Nuku. Pesan
  awalnya sudah memuat kode kartu, jadi tidak perlu bertanya "kartu yang mana".
  Nomornya diatur lewat `WHATSAPP_NUMBER` di `.env`; kosongkan untuk menyembunyikan
  tombolnya.
- **Pencatatan hit tidak boleh menghambat redirect.** Ditulis lewat background task
  dengan session sendiri; kalau gagal, redirect pelanggan tetap jalan.
- **IP address tidak disimpan.** Hanya `user_agent` (dipotong 255 karakter), cukup
  untuk membedakan Android vs iPhone secara kasar.
- **QR pakai error correction level Q** supaya masih terbaca walau akrilik tergores
  atau sebagian tertutup.
- **Isi QR sama persis dengan URL yang ditulis di NFC tag.** Default-nya huruf
  kecil apa adanya, 33x33 modul. Ini penting saat menelusuri masalah: satu kartu
  punya satu string, bukan dua versi yang berbeda huruf besar-kecilnya.
- **Mode padat tersedia, tapi bukan default.** `?compact=true` mengapitalkan
  scheme + domain saja sehingga QR turun ke 29x29 modul, dan **slug tetap utuh**
  karena hanya bagian yang case-insensitive menurut spesifikasi URL yang diubah.
  Pada cetakan 30 mm, 33x33 menghasilkan 0,73 mm per modul sementara 29x29
  memberi 0,81 mm — keduanya jauh di atas ambang aman kamera HP (~0,4 mm), jadi
  mode padat baru relevan kalau QR harus dicetak sangat kecil.

## Deployment

Kondisi VPS saat ini: Ubuntu 24.04, Python 3.12, Nginx 1.24, MariaDB, sertifikat
Let's Encrypt untuk `go.nukustudio.id`, dan unit systemd `go-nukustudio.service`
semuanya sudah terpasang. Yang tersisa hanya mengisi direktori aplikasinya.

Konfigurasi di [`deploy/`](deploy) adalah salinan dari apa yang sudah terpasang di
server, disimpan supaya perubahannya terlacak.

### 1. Kode aplikasi

```bash
cd /var/www/go.nukustudio.id
git clone <repo> .          # atau rsync dari lokal
```

Struktur akhir harus: `app/`, `alembic/`, `alembic.ini`, `run.py`, `.env`.
`run.py` adalah entry point yang dipanggil systemd.

### 2. Virtualenv

```bash
cd /var/www/go.nukustudio.id
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

Jangan pasang `requirements-dev.txt` di server — isinya hanya untuk dev lokal.

### 3. File `.env`

Variabel yang dibaca aplikasi: `DATABASE_URL`, `ADMIN_API_KEY`, `BASE_URL`, `PORT`,
`DEBUG`, dan `GOOGLE_PLACES_API_KEY`. Yang terakhir boleh dikosongkan — kalau kosong,
`POST /admin/lookup-place` membalas `503` dengan pesan jelas, sementara endpoint lain
tetap jalan normal.

> **Penting di VPS.** `.env.example` default-nya SQLite supaya dev lokal langsung
> jalan. Di server, komentari baris SQLite dan aktifkan baris `mysql+aiomysql://...`
> — kalau terlewat, aplikasi akan diam-diam menulis ke file `dev.db` alih-alih ke
> MariaDB.

```bash
cd /var/www/go.nukustudio.id
cp .env.example .env
openssl rand -hex 32        # tempel hasilnya ke ADMIN_API_KEY
nano .env
chown www-data:www-data .env && chmod 600 .env
```

Isi `DATABASE_URL` dengan password yang `@`-nya sudah di-encode jadi `%40`.
`.env` harus bisa dibaca `www-data` karena service jalan sebagai user itu.

### 4. Migrasi database

```bash
cd /var/www/go.nukustudio.id
venv/bin/alembic upgrade head
```

Kalau muncul `1050 Table 'review_links' already exists`, hapus dulu tabel lama
(lihat bagian *Setup database produksi*), lalu ulangi.

### 5. Jalankan service

```bash
chown -R www-data:www-data /var/www/go.nukustudio.id
systemctl daemon-reload
systemctl enable --now go-nukustudio
systemctl status go-nukustudio
```

### 6. Verifikasi

```bash
curl -s https://go.nukustudio.id/health
# {"status":"ok","base_url":"https://go.nukustudio.id"}
```

Kalau gagal, urutan pengecekan: `journalctl -u go-nukustudio -n 50` (aplikasi) →
`ss -tlnp | grep 8000` (sudah listen?) → `/var/log/nginx/go.nukustudio.id.error.log`
(proxy).

### 7. Uji alur lengkap sekali sebelum produksi

Jangan kirim apa pun ke percetakan sebelum satu kartu terbukti jalan dari ujung ke
ujung. Ganti `$KEY` dengan `ADMIN_API_KEY` di `.env` server.

```bash
curl -s -X POST https://go.nukustudio.id/admin/slugs/batch \
  -H "X-Admin-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"count":1,"batch_label":"batch-uji"}'
```

Catat `slug` dan `setup_url` dari responsnya, lalu periksa berurutan:

1. Buka `https://go.nukustudio.id/r/{slug}` → harus muncul halaman **"Kartu belum
   aktif"**, bukan 404 dan bukan form aktivasi.
2. Buka `setup_url` di HP → form aktivasi muncul. Isi dengan link Google Review
   mana pun untuk uji coba, submit.
3. Buka lagi `https://go.nukustudio.id/r/{slug}` → sekarang harus **langsung
   melompat** ke link tujuan.
4. Buka `setup_url` sekali lagi → harus sudah **tidak valid**. Kalau masih membuka
   form, ada yang salah pada pengecekan status — jangan lanjut produksi.
5. Ambil QR-nya, cetak seukuran akrilik sebenarnya, lalu **scan dari HP betulan**
   (Android dan iPhone, kamera bawaan).

Setelah lolos, nonaktifkan kartu uji itu:

```bash
curl -s -X PATCH https://go.nukustudio.id/admin/links/{slug} \
  -H "X-Admin-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"status":"inactive"}'
```

### Catatan Cloudflare

Record `go` sengaja **DNS-only (abu-abu)**, karena SSL zona `nukustudio.id` memakai
mode Flexible sementara subdomain ini punya sertifikat Let's Encrypt sendiri. Kalau
proxy Cloudflare diaktifkan untuk `go`, mode SSL-nya harus diubah ke **Full (strict)**
lewat Configuration Rule khusus subdomain ini — Flexible akan bentrok dengan redirect
80 → 443 di Nginx dan menghasilkan redirect loop.

## Backup database

Slug di `review_links` sudah tercetak permanen di akrilik klien. Kalau database ini
hilang, setiap kartu yang sudah beredar mati selamanya dan satu-satunya pemulihan
adalah mencetak ulang semuanya — jadi backup di sini bukan formalitas.

Script dan jadwalnya ada di [`deploy/backup-db.sh`](deploy/backup-db.sh) dan
[`deploy/nuku-redirect-backup.cron`](deploy/nuku-redirect-backup.cron).

### Pasang

```bash
install -m 755 /var/www/go.nukustudio.id/deploy/backup-db.sh /usr/local/bin/nuku-backup-db.sh
install -m 644 /var/www/go.nukustudio.id/deploy/nuku-redirect-backup.cron /etc/cron.d/nuku-redirect-backup
```

Uji sekali secara manual sebelum mengandalkan cron:

```bash
/usr/local/bin/nuku-backup-db.sh
```

Outputnya harus satu baris `OK` dengan ukuran file dan jumlah baris INSERT.

### Yang dijaga script ini

- **Tulis ke `.tmp` dulu**, baru di-`mv`. File setengah jadi tidak pernah terlihat
  seperti backup yang sah kalau prosesnya mati di tengah.
- **Verifikasi isi, bukan cuma exit code.** Dump yang tidak memuat
  `CREATE TABLE review_links` dianggap gagal dan langsung dihapus. Backup "berhasil"
  tapi kosong adalah cara paling umum orang mengira dirinya punya cadangan.
- **Hapus yang lama paling akhir**, setelah yang baru terbukti valid.
- **`--single-transaction`**, jadi redirect klien tetap jalan selama backup.
- **Tanpa password di file mana pun** — cron jalan sebagai root, dan root di MariaDB
  Ubuntu memakai unix_socket auth.

Retensi 30 hari, tersimpan di `/var/backups/nuku-redirect/` (mode 700).

### Restore

```bash
systemctl stop go-nukustudio
```

```bash
zcat /var/backups/nuku-redirect/nuku_redirect-YYYYMMDD-HHMMSS.sql.gz | mysql
```

```bash
systemctl start go-nukustudio && curl -s https://go.nukustudio.id/health
```

Dump dibuat dengan `--databases`, jadi sudah memuat `CREATE DATABASE` dan
`DROP TABLE` — tidak perlu menyiapkan database kosong lebih dulu.

### Batasnya

Backup ini ada di **VPS yang sama** dengan databasenya. Itu melindungi dari salah
`DROP`, korupsi tabel, dan salah migrasi — **tapi tidak** dari kehilangan VPS-nya
sendiri. Sesekali tarik salinannya ke mesin lokal:

```bash
scp root@187.127.110.129:/var/backups/nuku-redirect/*.sql.gz .
```

Sekali sebulan sudah jauh lebih baik daripada tidak sama sekali.

## Panel kerja admin

Swagger di `/admin/docs` menampilkan endpoint, bukan pekerjaan. Untuk kerja harian
pakai **`/admin/panel`**: masuk sekali dengan admin key, lalu bekerja dari daftar
kartu.

| Kebutuhan | Di panel |
|---|---|
| Lihat kondisi stok | Tiga angka di atas: stok, aktif, nonaktif |
| Cari kartu | Kotak cari (slug atau nama bisnis) + filter status & batch |
| Tulis NFC tag | Mode **Tulis NFC** — slug besar, URL siap salin, centang per kartu |
| Kirim link aktivasi | Tombol **Pesan aktivasi** — pesan WhatsApp lengkap, tinggal salin |
| Aktivasi oleh admin | Tombol **Aktifkan sendiri** — isi nama bisnis + link, kartu langsung hidup |
| Buat batch | Tombol **Batch baru** — token otomatis terunduh sebagai JSON |
| Ubah tujuan / nonaktifkan | Tombol di baris kartu yang sudah aktif |
| Unduh QR | Per kartu, atau satu ZIP mengikuti filter yang sedang aktif |

Centang di mode Tulis NFC disimpan di `localStorage` browser itu saja &mdash; menutup
halaman di tengah tumpukan 50 tag tidak menghilangkan progres, tapi progres itu juga
tidak ikut kalau Anda pindah perangkat.

### Soal keamanan halaman ini

`/admin/panel` sengaja tidak dilindungi `X-Admin-Key`, karena browser tidak bisa
mengirim header saat URL diketik biasa. Yang dikirim server hanyalah kerangka halaman
**tanpa data sedikit pun**; seluruh isinya diambil lewat `fetch()` yang barulah
menyertakan header itu. Gerbangnya tetap di endpoint `/admin/*` yang membawa data.

Admin key disimpan di `localStorage` supaya tidak perlu diketik ulang tiap kali. Di
perangkat bersama, tekan **Keluar** setelah selesai.

## Alur kerja: dua fase

### Fase 1 — Produksi (sebelum ada klien)

1. `POST /admin/slugs/batch` dengan `count` sesuai jumlah kartu yang mau dicetak.
   Server mengembalikan pasangan `slug` + `activation_token` untuk tiap kartu.
2. `GET /admin/qr/export?batch_label=batch-2026-09` → satu ZIP berisi semua QR SVG,
   langsung kirim ke percetakan akrilik.
3. Tulis NFC tag satu per satu dengan `https://go.nukustudio.id/r/{slug}` masing-masing.
   Bagian ini memang manual, tidak bisa diotomasi dari sisi software.
4. Kartu masuk stok. Kalau di-scan sekarang, muncul halaman "kartu belum aktif" — wajar.

**Simpan pasangan slug ↔ token di tempat aman** (spreadsheet privat). Token tidak pernah
dicetak di kartu, dan ZIP untuk percetakan sengaja tidak memuatnya.

### Fase 2 — Aktivasi (saat closing)

1. Ambil satu kartu polos dari stok, catat slug-nya dengan nama klien.
2. Ambil link aktivasinya: `GET /admin/links/{slug}` → field `setup_url`.
3. Kirim link itu ke klien lewat WA/japri — terpisah sepenuhnya dari kartu fisiknya.
4. Klien isi nama bisnis + link Google Review, submit. Kartu langsung hidup.
5. Link aktivasi otomatis mati setelah dipakai.

Butuh Place ID klien? `POST /admin/lookup-place` dengan nama bisnis + alamat lengkap.

### Setelah aktif

- Klien pindah lokasi / Place ID berubah → `PATCH /admin/links/{slug}` (lewat admin,
  bukan lewat `/setup` — rutenya sudah tertutup).
- Klien berhenti → `PATCH` dengan `{"status": "inactive"}`.
- Laporan retainer → `GET /admin/links/{slug}/stats`.

## Belum masuk scope (bisa nanti)

- QR dengan logo/warna custom (`segno` atau Pillow).
- Dashboard admin berbasis UI — sekarang cukup lewat `api.http`/curl/Postman.
- Multi-user auth — baru perlu kalau ada admin selain Amar.
- Portal akun klien (Opsi 3) — supaya klien bisa ganti link & lihat statistik sendiri
  tanpa lewat admin. Arah jangka panjang, idealnya dibangun bersamaan dengan dashboard
  hosting klien di VPS yang sama.
