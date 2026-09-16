"""Uji alur ujung-ke-ujung, tanpa perlu MariaDB atau server berjalan.

Jalankan dari akar project:

    python tests/smoke.py

Memakai database SQLite sementara yang dibuat dan dihapus sendiri, dan
memanggil aplikasi langsung lewat ASGI — jadi aman dijalankan kapan saja,
termasuk saat service produksi sedang hidup.

Butuh requirements-dev.txt (aiosqlite + httpx).
"""

import asyncio
import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AKAR))

DB = AKAR / "tests-smoke.db"
BASE = "https://go.nukustudio.id"
KEY = "kunci-tes-panjang-sekali"

os.environ.update(
    DATABASE_URL=f"sqlite+aiosqlite:///{DB.as_posix()}",
    ADMIN_API_KEY=KEY,
    BASE_URL=BASE,
    GOOGLE_PLACES_API_KEY="",
    WHATSAPP_NUMBER="6282394707711",
)

import httpx  # noqa: E402
from httpx import ASGITransport  # noqa: E402

H = {"X-Admin-Key": KEY}
gagal = []


def check(label, cond, extra=""):
    print(("  PASS " if cond else "  FAIL ") + label + ("" if cond else " | " + str(extra)))
    if not cond:
        gagal.append(label)


def bagian(judul):
    print("\n" + judul)


async def jalan():
    from app.main import app
    from app.qr import compact_payload
    from app.schemas import normalize_url

    tr = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=tr, base_url="http://test") as c:

        bagian("Auth")
        check("health 200", (await c.get("/health")).status_code == 200)
        check("admin tanpa key -> 401", (await c.get("/admin/links")).status_code == 401)
        check("admin key salah -> 401",
              (await c.get("/admin/links", headers={"X-Admin-Key": "salah"})).status_code == 401)

        bagian("Fase 1 - produksi stok")
        r = await c.post("/admin/slugs/batch", json={"count": 5}, headers=H)
        check("batch 201", r.status_code == 201, r.text)
        batch = r.json()
        check("batch_label otomatis dari tanggal", batch["batch_label"].startswith("batch-20"),
              batch["batch_label"])
        check("jumlah sesuai", batch["count"] == 5 and len(batch["items"]) == 5)
        slugs = [i["slug"] for i in batch["items"]]
        toks = [i["activation_token"] for i in batch["items"]]
        check("slug unik", len(set(slugs)) == 5, slugs)
        check("slug URL-safe huruf kecil", all(s.islower() and s.isalnum() for s in slugs), slugs)
        check("tanpa karakter ambigu 0/1/i/l/o",
              not any(set(s) & set("01ilo") for s in slugs), slugs)
        check("token unik dan panjang", len(set(toks)) == 5 and all(len(t) >= 20 for t in toks))
        check("setup_url benar",
              batch["items"][0]["setup_url"] == f"{BASE}/setup/{slugs[0]}?key={toks[0]}")
        check("redirect_url tidak membawa token", "key=" not in batch["items"][0]["redirect_url"])

        r = await c.post("/admin/slugs/batch",
                         json={"count": 2, "batch_label": "Batch-Khusus-01"}, headers=H)
        check("batch_label dinormalisasi", r.json()["batch_label"] == "batch-khusus-01", r.text)
        check("count=0 -> 422",
              (await c.post("/admin/slugs/batch", json={"count": 0}, headers=H)).status_code == 422)
        check("batch_label invalid -> 422",
              (await c.post("/admin/slugs/batch",
                            json={"count": 1, "batch_label": "batch 2026!"},
                            headers=H)).status_code == 422)

        s0, t0 = slugs[0], toks[0]

        bagian("Kartu stok - halaman belum aktif")
        fb = await c.get("/r/" + s0)
        check("unassigned -> fallback 200, bukan 302",
              fb.status_code == 200 and "belum aktif" in fb.text.lower(), fb.status_code)
        check("/r/ abaikan parameter key",
              (await c.get(f"/r/{s0}?key={t0}")).status_code == 200)
        check("fallback memuat link wa.me", "https://wa.me/" in fb.text)
        check("pesan WA membawa kode kartu", "Kode%20kartu%3A%20" + s0 in fb.text)
        check("kode kartu terlihat pengunjung", s0 in fb.text)
        check("slug tak dikenal tetap dapat tombol WA",
              "https://wa.me/" in (await c.get("/r/slug-tidak-ada")).text)
        jahat = await c.get("/r/%3Cscript%3Ealert(1)%3C/script%3E")
        check("slug aneh tidak ter-render mentah (XSS)", "<script>alert" not in jahat.text)

        bagian("Fase 2 - aktivasi bertoken")
        check("setup tanpa key -> 404",
              (await c.get("/setup/" + s0)).status_code == 404)
        r_salah = await c.get(f"/setup/{s0}?key=token-ngawur")
        r_hantu = await c.get(f"/setup/slug-hantu?key={t0}")
        check("token salah -> 404", r_salah.status_code == 404)
        check("slug tidak ada -> 404", r_hantu.status_code == 404)
        check("pesan gagal identik, tidak bocorkan syarat mana yang gagal",
              r_salah.text == r_hantu.text)

        r = await c.get(f"/setup/{s0}?key={t0}")
        check("token benar -> form 200", r.status_code == 200 and "<form" in r.text)
        check("token hanya muncul sekali (hidden input)", r.text.count(t0) == 1)

        check("submit token salah -> 404",
              (await c.post("/setup/" + s0, data={"key": "salah", "business_name": "X",
                                                  "destination_url": "https://g.page/r/A/review"})).status_code == 404)
        r = await c.post("/setup/" + s0, data={"key": t0, "business_name": "Warkop Sinar",
                                               "destination_url": "bukan url sama sekali"})
        check("URL ngawur -> 400 dan form lagi", r.status_code == 400 and "<form" in r.text)

        # Klien sering menempel link tanpa skema — harus dilengkapi, bukan ditolak.
        r = await c.post("/setup/" + s0, data={"key": t0, "business_name": "Warkop Sinar",
                                               "destination_url": "g.page/r/ABCdef/review"})
        check("aktivasi terima link tanpa https:// (dilengkapi)",
              r.status_code == 200 and "aktif" in r.text.lower(), r.status_code)

        d = (await c.get("/admin/links/" + s0, headers=H)).json()
        check("status jadi active", d["status"] == "active", d)
        check("activated_at terisi", d["activated_at"] is not None)
        check("skema dilengkapi jadi https://",
              d["destination_url"] == "https://g.page/r/ABCdef/review", d["destination_url"])
        check("setup_url ditutup setelah aktif", d["setup_url"] is None)

        r = await c.get("/r/" + s0, headers={"user-agent": "iPhone"})
        check("kartu aktif -> 302",
              r.status_code == 302 and r.headers.get("location") == "https://g.page/r/ABCdef/review",
              r.status_code)
        check("slug KAPITAL tetap 302", (await c.get("/r/" + s0.upper())).status_code == 302)
        check("link setup mati setelah dipakai",
              (await c.get(f"/setup/{s0}?key={t0}")).status_code == 404)

        bagian("Admin - kelola kartu")
        r = await c.patch("/admin/links/" + s0, json={"status": "inactive"}, headers=H)
        check("patch inactive", r.status_code == 200 and r.json()["status"] == "inactive", r.text)
        check("inactive -> fallback", (await c.get("/r/" + s0)).status_code == 200)
        check("aktifkan lagi",
              (await c.patch("/admin/links/" + s0, json={"status": "active"},
                             headers=H)).json()["status"] == "active")

        # Bug yang muncul di panel: URL tanpa skema membalas 422.
        r = await c.patch("/admin/links/" + s0,
                          json={"destination_url": "search.google.com/local/writereview?placeid=ChIJ1U"},
                          headers=H)
        check("patch terima URL tanpa https:// (dilengkapi)", r.status_code == 200, r.text)
        check("hasilnya tersimpan dengan https://",
              r.json()["destination_url"] == "https://search.google.com/local/writereview?placeid=ChIJ1U",
              r.json().get("destination_url"))
        check("redirect ikut tujuan baru",
              (await c.get("/r/" + s0)).headers.get("location")
              == "https://search.google.com/local/writereview?placeid=ChIJ1U")
        check("URL benar-benar ngawur tetap ditolak 422",
              (await c.patch("/admin/links/" + s0, json={"destination_url": "??"},
                             headers=H)).status_code == 422)

        check("active tanpa destination_url -> 400",
              (await c.patch("/admin/links/" + slugs[1], json={"status": "active"},
                             headers=H)).status_code == 400)
        check("patch kosong -> 400",
              (await c.patch("/admin/links/" + s0, json={}, headers=H)).status_code == 400)
        check("patch slug tidak ada -> 404",
              (await c.patch("/admin/links/hantu", json={"status": "inactive"},
                             headers=H)).status_code == 404)
        check("DELETE tidak tersedia",
              (await c.delete("/admin/links/" + s0, headers=H)).status_code == 405)

        bagian("Daftar dan filter")
        check("list semua = 7", len((await c.get("/admin/links", headers=H)).json()) == 7)
        check("filter unassigned = 6",
              len((await c.get("/admin/links?status=unassigned", headers=H)).json()) == 6)
        check("filter active = 1",
              len((await c.get("/admin/links?status=active", headers=H)).json()) == 1)
        rl = await c.get("/admin/links?batch_label=batch-khusus-01", headers=H)
        check("filter batch_label = 2", len(rl.json()) == 2)
        check("filter batch_label case-insensitive (sama di MariaDB dan SQLite)",
              len((await c.get("/admin/links?batch_label=BATCH-KHUSUS-01",
                               headers=H)).json()) == 2)
        check("list tidak membocorkan token", "activation_token" not in rl.text)

        bagian("QR")
        url_kartu = f"{BASE}/r/{s0}"
        check("payload default = URL apa adanya (sama dengan NFC tag)",
              compact_payload(url_kartu) != url_kartu)
        check("payload compact tetap memuat slug asli",
              "/r/" + s0 in compact_payload(url_kartu)
              and s0.upper() not in compact_payload(url_kartu), compact_payload(url_kartu))
        check("payload compact mengapitalkan domain saja",
              compact_payload(url_kartu).startswith("HTTPS://GO.NUKUSTUDIO.ID/r/"))
        r = await c.get("/admin/links/" + s0 + "/qr", headers=H)
        check("qr SVG 200",
              r.status_code == 200 and r.headers["content-type"].startswith("image/svg"))
        check("qr compact menghasilkan gambar berbeda",
              (await c.get("/admin/links/" + s0 + "/qr?compact=true", headers=H)).text != r.text)

        bagian("Export ZIP")
        r = await c.get("/admin/qr/export?batch_label=batch-khusus-01", headers=H)
        check("export ZIP 200",
              r.status_code == 200 and r.headers["content-type"] == "application/zip")
        check("nama file pakai label", "qr-batch-khusus-01.zip" in r.headers.get("content-disposition", ""))
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        nama = sorted(zf.namelist())
        check("berisi 2 SVG bernama slug",
              len(nama) == 2 and all(n.endswith(".svg") for n in nama), nama)
        isi = zf.read(nama[0]).decode()
        check("isinya SVG", "<svg" in isi)
        check("ZIP tidak memuat token (tidak boleh ke percetakan)",
              not any(t in isi for t in toks))
        check("export by status = 6 file",
              len(zipfile.ZipFile(io.BytesIO(
                  (await c.get("/admin/qr/export?status=unassigned", headers=H)).content
              )).namelist()) == 6)
        check("filter kosong -> 404",
              (await c.get("/admin/qr/export?batch_label=tidak-ada", headers=H)).status_code == 404)

        bagian("Admin aktifkan sendiri (tombol di panel)")
        # Blueprint mengizinkan admin mengisikan data klien sendiri. Panel
        # mengirim nama, tujuan, dan status dalam SATU patch — harus menyatu,
        # karena server menolak status=active tanpa destination_url.
        s2, t2 = slugs[2], toks[2]
        check("link setup s2 masih hidup sebelum diaktifkan",
              (await c.get(f"/setup/{s2}?key={t2}")).status_code == 200)
        r = await c.patch("/admin/links/" + s2, json={
            "business_name": "Kopi Pagi",
            "destination_url": "g.page/r/XYZ/review",
            "status": "active",
        }, headers=H)
        check("aktivasi oleh admin dalam satu PATCH", r.status_code == 200, r.text)
        d2 = r.json()
        check("nama, tujuan, dan status tersimpan",
              d2["business_name"] == "Kopi Pagi"
              and d2["destination_url"] == "https://g.page/r/XYZ/review"
              and d2["status"] == "active", d2)
        check("activated_at ikut terisi", d2["activated_at"] is not None)
        check("kartu langsung meredirect",
              (await c.get("/r/" + s2)).headers.get("location") == "https://g.page/r/XYZ/review")
        check("link setup mati setelah diaktifkan admin",
              (await c.get(f"/setup/{s2}?key={t2}")).status_code == 404)

        bagian("Statistik dan Places")
        await asyncio.sleep(0.3)
        st = (await c.get("/admin/links/" + s0 + "/stats", headers=H)).json()
        check("stats memuat status", st["status"] == "active", st)
        check("stats hitung 3 hit redirect sukses (fallback tidak dihitung)",
              st["total_hits"] == 3, st)
        check("lookup tanpa API key -> 503",
              (await c.post("/admin/lookup-place",
                            json={"business_name": "X", "full_address": "Y"},
                            headers=H)).status_code == 503)

        bagian("normalize_url")
        for masuk, keluar in [
            ("g.page/r/ABC/review", "https://g.page/r/ABC/review"),
            ("https://g.page/r/ABC/review", "https://g.page/r/ABC/review"),
            ("http://contoh.id/r", "http://contoh.id/r"),
            ("  www.google.com/maps  ", "https://www.google.com/maps"),
        ]:
            check(f"{masuk.strip()!r} -> skema benar", normalize_url(masuk) == keluar,
                  normalize_url(masuk))

    from app.database import engine
    await engine.dispose()


def main():
    if DB.exists():
        DB.unlink()
    hasil = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=AKAR, capture_output=True, text=True, env=os.environ,
    )
    if hasil.returncode != 0:
        print("Gagal menyiapkan database uji:\n" + hasil.stderr)
        return 1

    try:
        asyncio.run(jalan())
    finally:
        # Windows menolak menghapus file yang masih dipegang engine.
        if DB.exists():
            try:
                DB.unlink()
            except PermissionError:
                print(f"(catatan: {DB.name} belum bisa dihapus, hapus manual)")

    print()
    if gagal:
        print(f"=== {len(gagal)} GAGAL ===")
        for g in gagal:
            print("  - " + g)
        return 1
    print("=== SEMUA LULUS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
