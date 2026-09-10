#!/usr/bin/env bash
#
# Deploy update ke VPS. Jalankan sebagai root di /var/www/go.nukustudio.id:
#   ./deploy/update.sh
#
# Menggantikan ritual scp: tarik perubahan, samakan dependency, jalankan
# migrasi, restart, lalu buktikan layanannya benar-benar hidup.

set -euo pipefail

APP=/var/www/go.nukustudio.id
cd "$APP"

echo "== tarik perubahan =="
# --ff-only: kalau ada perubahan lokal yang menyimpang, berhenti dengan jelas
# daripada membuat commit merge di server.
git pull --ff-only

echo "== dependency =="
venv/bin/pip install -q -r requirements.txt

echo "== migrasi database =="
venv/bin/alembic upgrade head

echo "== izin berkas =="
# Service jalan sebagai www-data, jadi user itu harus bisa membaca semuanya.
chown -R www-data:www-data "$APP"
# .env memuat admin key dan password database.
chmod 600 "$APP/.env"

echo "== restart =="
systemctl restart go-nukustudio

# Beri waktu uvicorn mengikat port sebelum diperiksa.
for _ in 1 2 3 4 5; do
    sleep 1
    if systemctl is-active --quiet go-nukustudio; then break; fi
done

if ! systemctl is-active --quiet go-nukustudio; then
    echo "GAGAL: service tidak hidup. Lihat sebabnya:" >&2
    journalctl -u go-nukustudio -n 30 --no-pager >&2
    exit 1
fi

echo "== verifikasi =="
# Lewat domain publik, bukan localhost — sekaligus menguji Nginx dan SSL.
curl -fsS https://go.nukustudio.id/health
echo
echo "Selesai."
