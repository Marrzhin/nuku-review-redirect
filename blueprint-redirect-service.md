# Blueprint: Layanan Redirect Google Review (QR + NFC)

## Tujuan
Layanan backend yang jadi satu titik kontrol untuk semua link Google Review klien Nuku Creative Studio. QR code dan NFC tag yang sudah tercetak/tertanam di akrilik klien tidak pernah encode URL Google secara langsung — semua mengarah ke `nuku.std/r/{slug}`, yang di-redirect oleh layanan ini ke tujuan asli. Kalau Place ID Google berubah atau rusak, cukup update di sini, tanpa cetak ulang produk fisik.

**Model bisnis yang diikuti — provisioning dulu, aktivasi belakangan:** kartu NFC+QR dicetak massal di awal sebagai stok polos (slug sudah ada di sistem, tapi belum terhubung ke bisnis mana pun). Saat closing dengan klien baru, kartu polos itu "diaktivasi" — dipasangkan ke link Google Review klien tersebut. Fisik kartunya tidak pernah dicetak ulang antar dua fase ini.

## Keputusan stack
- **Backend**: FastAPI (Python) — konsisten dengan stack automation yang sudah dipakai.
- **Database**: MariaDB/MySQL 8 + SQLAlchemy 2.x (async) + Alembic — dipilih karena sudah jadi stack yang familiar, dan VPS ini nanti juga menjalankan MySQL/MariaDB untuk situs WordPress klien. Satu instance database, schema terpisah untuk layanan ini, mengurangi jumlah moving parts di server.
- **QR generation**: library `qrcode` Python dengan output SVG (vector, aman untuk cetak di ukuran berapa pun tanpa pecah).
- **Auth admin**: API key sederhana di header (`X-Admin-Key`), bukan sistem user penuh — ini alat internal untuk satu admin (Amar), belum perlu multi-user login.
- **Deployment**: dijalankan sebagai service via `uvicorn`, listen di `127.0.0.1:PORT` (bukan public), diteruskan oleh Nginx sebagai reverse proxy dengan SSL.

## Skema database

### Tabel `review_links`
| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | INT, PK, auto increment | |
| `slug` | VARCHAR(64), UNIQUE, NOT NULL | contoh: `warkop-sinar` — dibuat saat batch produksi, dicetak ke QR/NFC **sebelum** ada klien |
| `status` | ENUM('unassigned','active','inactive'), DEFAULT 'unassigned' | `unassigned` = kartu polos di stok; `active` = sudah terhubung ke bisnis; `inactive` = klien berhenti/nonaktif sementara |
| `activation_token` | VARCHAR(48), NULLABLE | dibuat sekali saat batch produksi, dipakai untuk validasi link aktivasi. **Tidak pernah dicetak di kartu** — dikirim terpisah ke klien saat closing |
| `batch_label` | VARCHAR(32), NOT NULL | contoh: `batch-2026-09`. Diisi otomatis dari tanggal saat `POST /admin/slugs/batch` dipanggil — untuk lacak cepat kalau ada masalah spesifik ke satu batch cetakan (misal NFC dari supplier tertentu bermasalah) |
| `business_name` | VARCHAR(255), NULLABLE | kosong selama `status=unassigned`, diisi saat aktivasi |
| `destination_url` | TEXT, NULLABLE | kosong selama `status=unassigned`, diisi saat aktivasi (link Google Review asli) |
| `created_at` | DATETIME | saat slug dibuat (fase produksi, bukan aktivasi) |
| `activated_at` | DATETIME, NULLABLE | diisi otomatis saat status berubah jadi `active` |
| `updated_at` | DATETIME | |

### Tabel `redirect_hits` (opsional, untuk analytics — bisa jadi value-add retainer)
| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | INT, PK, auto increment | |
| `link_id` | INT, FK ke `review_links.id` | |
| `hit_at` | DATETIME | |
| `user_agent` | VARCHAR(255), nullable | untuk deteksi kasar Android vs iPhone |

Catatan privasi: jangan simpan IP address mentah. Kalau butuh dedup/analitik lokasi kasar, hash IP-nya (misal SHA256 + salt) — bukan wajib untuk versi pertama, boleh di-skip dulu.

## Endpoint API

| Method & path | Fungsi | Auth |
|---|---|---|
| `GET /r/{slug}` | Redirect publik — **inilah URL yang tercetak di QR/NFC**, tidak pernah menerima token. Cek `status`: kalau `active` → HTTP **302** (bukan 301 — penting, supaya update tujuan langsung berlaku tanpa masalah cache browser/scanner) ke `destination_url`, catat hit. Kalau `unassigned` atau `inactive` → tampilkan halaman fallback sederhana ("Link belum aktif, hubungi provider"), bukan 404 polos dan **bukan form aktivasi**. | Publik |
| `POST /admin/slugs/batch` | Input: jumlah kartu (misal 50), opsional `batch_label` (default: tanggal hari ini, format `batch-YYYY-MM`). Generate `slug` + `activation_token` sekaligus untuk stok produksi, status otomatis `unassigned`. Balikin list `{slug, activation_token}` untuk disiapkan ke percetakan akrilik & NFC writer. | API key |
| `GET /admin/qr/export?batch_label=...` (atau `?status=unassigned`) | Generate **satu file ZIP** berisi semua QR SVG yang cocok filter, nama file per slug (misal `warkop-a1.svg`). Ini yang langsung dikirim ke percetakan untuk satu batch — tidak perlu download satu-satu. | API key |
| `GET /admin/links` | List semua link, termasuk kolom `status` — jadi bisa lihat mana yang masih stok (`unassigned`) dan mana yang sudah jalan (`active`) | API key |
| `GET /admin/links/{slug}` | Detail satu link | API key |
| `PATCH /admin/links/{slug}` | Update `destination_url` dan/atau `status` (dipakai admin, misal set `inactive` kalau klien berhenti) | API key |
| `GET /admin/links/{slug}/qr` | Generate & return QR code (SVG) untuk `nuku.std/r/{slug}`, siap didownload untuk dicetak | API key |
| `GET /admin/links/{slug}/stats` | Jumlah hit total + 7 hari terakhir (pakai tabel `redirect_hits`) | API key |
| `POST /admin/lookup-place` | Input: `business_name`, `full_address`. Cari Place ID otomatis lewat Google Places API, supaya tidak perlu buka Google Maps manual tiap onboarding klien baru. Lihat detail di bagian "Integrasi Google Places API" di bawah. | API key |
| `GET /setup/{slug}?key={activation_token}` | Tampilkan form aktivasi (halaman HTML sederhana). Hanya tampil kalau `key` cocok dengan `activation_token` di database **dan** `status` masih `unassigned`. Selain itu → tampilkan pesan "link tidak valid/sudah dipakai". | Publik, dilindungi token (bukan API key) |
| `POST /setup/{slug}` | Submit form aktivasi: `business_name`, `destination_url`, `key`. Validasi sama seperti di atas, lalu set `status=active`, `activated_at=now()`. Setelah ini endpoint otomatis tidak bisa dipakai lagi untuk slug yang sama, karena status sudah bukan `unassigned`. | Publik, dilindungi token |

Sengaja **tidak ada endpoint hard-delete**. Slug yang sudah tercetak di akrilik fisik klien tidak boleh bisa hilang permanen secara tidak sengaja — kalau klien berhenti, cukup set `status=inactive`.

## Struktur folder yang disarankan

```
review-redirect/
├── app/
│   ├── main.py            # entrypoint FastAPI
│   ├── config.py          # baca env vars (DATABASE_URL, ADMIN_API_KEY, BASE_URL)
│   ├── database.py        # setup SQLAlchemy async engine + session
│   ├── models.py          # model ReviewLink, RedirectHit
│   ├── schemas.py         # Pydantic schemas request/response
│   ├── crud.py            # fungsi query database
│   ├── qr.py              # generate QR SVG per slug + fungsi zip banyak QR sekaligus untuk export batch
│   ├── places.py          # fungsi panggil Google Places API (lookup Place ID)
│   ├── routers/
│   │   ├── redirect.py    # GET /r/{slug}
│   │   ├── admin.py       # semua endpoint /admin/*, termasuk /admin/slugs/batch
│   │   └── setup.py       # GET & POST /setup/{slug} — form aktivasi publik bertoken
│   └── templates/
│       └── setup.html     # form aktivasi sederhana (business_name, destination_url)
├── alembic/                # migrations
├── alembic.ini
├── requirements.txt
├── .env.example
└── README.md
```

## Environment variables

```
DATABASE_URL=mysql+aiomysql://user:pass@localhost/nuku_redirect
ADMIN_API_KEY=ganti-dengan-key-acak-yang-panjang
BASE_URL=https://nuku.std
GOOGLE_PLACES_API_KEY=isi-dari-google-cloud-console
```

## Integrasi Google Places API (lookup Place ID otomatis)

**Tujuan**: mengganti proses manual (buka Google Maps/Place ID Finder tiap ada klien baru) dengan satu panggilan API di form onboarding sendiri.

**Endpoint Google yang dipakai**: Places API (New) — Text Search
`POST https://places.googleapis.com/v1/places:searchText`

**Aturan biaya yang WAJIB diikuti**: request harus pakai header `X-Goog-FieldMask: places.id` — **hanya minta field ID**, jangan tambahkan field lain (nama, alamat, rating, dll). Selama field mask dibatasi ke `places.id` saja, request ini masuk tier "IDs Only" yang **tidak dikenakan biaya berapa pun volumenya**. Menambah field lain otomatis memindahkan seluruh request ke tier berbayar (Pro/Enterprise), bukan cuma field tambahannya saja.

**Alur logika yang disarankan**:
1. Terima `business_name` + `full_address` dari admin.
2. Panggil Text Search dengan query gabungan `"{business_name} {full_address}"` dan FieldMask `places.id` saja (gratis).
3. Kalau hasil **persis 1 tempat** → langsung kembalikan `place_id` itu, siap dipakai bikin `review_links` baru.
4. Kalau hasil **0 tempat** → kembalikan pesan error, arahkan admin untuk isi Place ID manual (fallback ke Place ID Finder).
5. Kalau hasil **lebih dari 1 tempat** (nama bisnis umum/ambigu) → di titik ini saja, lakukan satu panggilan susulan dengan FieldMask lebih lengkap (`places.displayName,places.formattedAddress`) HANYA untuk kandidat-kandidat itu, supaya admin bisa lihat nama+alamat dan pilih manual yang benar. Ini akan kena biaya tier Pro, tapi karena cuma terjadi di kasus ambigu (jarang) dan hanya untuk beberapa kandidat, dampak biayanya minim — bukan dikenakan di setiap lookup.

**Prasyarat setup** (dilakukan sekali di awal, bukan bagian dari kode):
- Buat project di Google Cloud Console, aktifkan "Places API (New)".
- Wajib mengaktifkan billing (kartu pembayaran harus terpasang) meski tagihan aktual tetap Rp 0 selama field mask dijaga sesuai aturan di atas — ini syarat administratif Google, bukan indikasi akan kena biaya.
- Generate API key, batasi (restrict) key tersebut hanya untuk Places API dan idealnya hanya bisa diakses dari IP VPS produksi, supaya tidak disalahgunakan kalau bocor.

## Alur provisioning & aktivasi kartu (token per kartu)

Ini bagian paling penting untuk dipahami sebelum coding, karena mengubah urutan kerja dari asumsi awal ("buat data klien dulu, baru cetak") jadi kebalikannya ("cetak stok dulu, aktivasi belakangan").

**Fase 1 — Produksi (batch, sebelum ada klien):**
1. Panggil `POST /admin/slugs/batch` dengan jumlah kartu yang mau dicetak (misal 50). `batch_label` diisi otomatis (misal `batch-2026-09`) supaya batch ini bisa dilacak terpisah dari batch berikutnya.
2. Server generate 50 `slug` unik + 50 `activation_token` acak (pakai `secrets.token_urlsafe(16)` atau setara — cukup panjang supaya tidak bisa ditebak), status semua `unassigned`.
3. Panggil `GET /admin/qr/export?batch_label=batch-2026-09` untuk dapat satu file ZIP berisi 50 QR SVG sekaligus — ini yang dikirim ke percetakan akrilik. Untuk NFC, tulis manual tiap tag dengan URL `nuku.std/r/{slug}` masing-masing (proses ini tetap satu-satu, tidak bisa di-otomasi dari sisi software).
4. Kartu jadi, masuk stok. Di titik ini scan/tap kartu akan menampilkan halaman "belum aktif" (lihat `GET /r/{slug}` di atas) — wajar, karena memang belum ada klien.

**Fase 2 — Aktivasi (per klien, saat closing):**
1. Ambil satu kartu polos dari stok, catat pasangan slug-nya di spreadsheet dengan nama klien baru.
2. Kirim link privat ke klien (atau isi sendiri kalau kamu yang input): `https://nuku.std/setup/{slug}?key={activation_token}` — dikirim lewat WA/japri, terpisah sepenuhnya dari kartu fisiknya.
3. Klien (atau kamu) buka link itu, form aktivasi muncul (`GET /setup/{slug}`), isi `business_name` dan `destination_url` (link Google Review asli), submit (`POST /setup/{slug}`).
4. Server validasi `key` cocok dan status masih `unassigned`, lalu set `status=active`. Kartu fisik yang sama, dari titik ini, langsung mengarah ke halaman review Google setiap di-scan/tap.
5. Link `/setup/{slug}?key=...` otomatis tidak berfungsi lagi setelahnya — bukan karena tokennya dihapus, tapi karena pengecekan status `unassigned` sudah gagal begitu jadi `active`. Ini bikin token otomatis "sekali pakai" tanpa perlu logika expiry terpisah.

**Kenapa ini aman:** URL yang tercetak di kartu (`/r/{slug}`) dan URL aktivasi (`/setup/{slug}?key=...`) adalah dua rute yang benar-benar terpisah. Siapa pun yang menemukan/scan kartu fisik tidak akan bisa mengakses form aktivasi, karena token itu tidak pernah ada di kartu — hanya kamu yang tahu dan yang mengirimkannya secara pribadi ke klien yang benar.

**Kalau klien mau ubah link Google Review-nya setelah aktif** (pindah lokasi, dsb): itu **tidak** lewat `/setup/{slug}` lagi (rutenya sudah tertutup otomatis), tapi lewat kamu via `PATCH /admin/links/{slug}` pakai API key. Ini keputusan desain yang disengaja — sekaligus alasan alami klien tetap butuh kamu sebagai partner setelah aktivasi awal, konsisten dengan model retainer bulanan.

**Roadmap (Opsi 3 — belum dibangun sekarang):** ke depan, kalau sudah ada cukup klien recurring yang butuh kelola sendiri (ganti link, lihat statistik scan, dll) tanpa harus minta ke kamu tiap kali, token sekali pakai ini bisa digantikan/dilengkapi dengan akun login klien di portal Nuku Studio — idealnya dibangun bersamaan dengan kebutuhan dashboard hosting website klien di VPS yang sama, bukan sistem terpisah. Belum masuk scope versi pertama ini.

## Hal yang wajib diperhatikan saat implementasi
1. Redirect **harus** HTTP 302, jangan 301.
2. Endpoint publik `/r/{slug}` tidak boleh butuh auth — ini yang dipanggil dari HP pelanggan lewat scan QR/tap NFC.
3. Slug harus di-generate atau divalidasi supaya URL-safe (huruf kecil, angka, strip) dan unik — tolak kalau sudah dipakai.
4. QR yang di-generate harus dalam format vector (SVG) supaya kualitasnya tetap bagus di ukuran cetak akrilik berapa pun.
5. Uvicorn listen di `127.0.0.1`, bukan `0.0.0.0` — akses publik hanya lewat Nginx.
6. `GET/POST /setup/{slug}` wajib validasi **dua syarat sekaligus**: `key` di query param cocok dengan `activation_token` di database, DAN `status` masih `unassigned`. Kalau salah satu gagal, tampilkan pesan generik ("link tidak valid atau sudah dipakai") — jangan bocorkan mana dari dua syarat itu yang gagal, supaya tidak membantu orang menebak token yang benar.
7. `GET /r/{slug}` (URL di kartu) tidak pernah membaca/menerima parameter `key` — jalur ini murni cek `status` lalu redirect atau tampilkan fallback. Jangan sampai logika token dari `/setup` tercampur ke rute ini.

## Belum termasuk di scope pertama (boleh nanti)
- QR dengan logo/warna custom (bisa tambah `segno` atau Pillow belakangan)
- Dashboard admin berbasis UI (untuk sekarang, admin endpoint via API key cukup dites lewat Postman/curl atau file `.http`)
- Multi-user auth (baru perlu kalau Marrzhin atau orang lain butuh akses admin juga)
- Portal akun client (Opsi 3) — arah jangka panjang setelah ada kebutuhan dashboard klien yang lebih luas, bukan bagian dari versi pertama ini
