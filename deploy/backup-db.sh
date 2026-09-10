#!/usr/bin/env bash
#
# Backup harian database nuku_redirect.
#
# Pasang di VPS sebagai /usr/local/bin/nuku-backup-db.sh (chmod 755),
# dijadwalkan lewat /etc/cron.d/nuku-redirect-backup.
#
# Kenapa ini penting: slug di tabel review_links sudah tercetak permanen di
# akrilik klien. Kalau database hilang, kartu yang sudah beredar mati selamanya
# dan satu-satunya pemulihan adalah cetak ulang semuanya.
#
# Tidak ada password di file ini: cron jalan sebagai root, dan root@localhost
# di MariaDB Ubuntu memakai unix_socket auth.

set -euo pipefail

DB=nuku_redirect
DIR=/var/backups/nuku-redirect
SIMPAN_HARI=30

mkdir -p "$DIR"
chmod 700 "$DIR"

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="$DIR/$DB-$STAMP.sql.gz"

# --single-transaction: konsisten tanpa mengunci tabel, jadi redirect klien
# tetap jalan selama backup berlangsung.
# Tulis ke .tmp dulu supaya file setengah jadi tidak pernah terlihat seperti
# backup yang sah kalau prosesnya mati di tengah.
mysqldump \
  --single-transaction \
  --quick \
  --routines \
  --events \
  --databases "$DB" \
  | gzip -9 > "$OUT.tmp"

mv "$OUT.tmp" "$OUT"
chmod 600 "$OUT"

# Verifikasi isinya, bukan cuma exit code. Backup yang "berhasil" tapi kosong
# adalah cara paling umum orang mengira dirinya punya cadangan.
#
# Sengaja pakai `grep -c`, BUKAN `grep -q`. Dengan `set -o pipefail`, `grep -q`
# keluar begitu menemukan kecocokan, `zcat` kena SIGPIPE (exit 141), dan
# pipeline-nya terbaca gagal — sehingga backup yang justru valid ikut terhapus.
# `grep -c` membaca seluruh input, jadi tidak pernah memicu SIGPIPE.
ADA=$(zcat "$OUT" | grep -c 'CREATE TABLE `review_links`' || true)
if [ "$ADA" -eq 0 ]; then
    echo "$(date -Is) GAGAL: dump tidak memuat tabel review_links" >&2
    rm -f "$OUT"
    exit 1
fi

JUMLAH=$(zcat "$OUT" | grep -c 'INSERT INTO `review_links`' || true)

# Hapus backup lama. Dijalankan paling akhir, supaya yang lama tidak pernah
# terhapus sebelum yang baru terbukti valid.
find "$DIR" -name "$DB-*.sql.gz" -type f -mtime +"$SIMPAN_HARI" -delete

echo "$(date -Is) OK $OUT ($(du -h "$OUT" | cut -f1), $JUMLAH baris INSERT review_links)"
