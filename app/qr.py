import io
import re
import zipfile
from collections.abc import Iterable

import qrcode
from qrcode.image.svg import SvgPathImage

# scheme + host saja; path dan seterusnya dibiarkan utuh.
_ORIGIN = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*://[^/]+)(.*)$")


def compact_payload(url: str) -> str:
    """Kapitalkan scheme + domain saja, biarkan path apa adanya.

    Mode alfanumerik QR hanya mendukung huruf besar, dan mode itu jauh lebih
    padat daripada mode byte. Mengapitalkan awalan URL memangkas QR dari 33x33
    jadi 29x29 modul, sementara **slug di path tetap persis seperti aslinya**
    — penting supaya isi QR tidak berbeda dari URL yang ditulis di NFC tag.

    Aman karena scheme dan host memang case-insensitive menurut spesifikasi
    URL, jadi mengapitalkannya tidak mengubah tujuan sedikit pun.
    """
    m = _ORIGIN.match(url)
    if not m:
        return url
    return m.group(1).upper() + m.group(2)


def make_qr_svg(url: str, *, compact: bool = False) -> bytes:
    """QR code format SVG (vector) — tetap tajam di ukuran cetak berapa pun.

    Error correction level Q: masih terbaca walau permukaan akrilik tergores
    atau sebagian tertutup, tanpa membuat modul terlalu rapat.

    Default `compact=False` meng-encode URL apa adanya: 33x33 modul, dan isi
    QR sama persis dengan URL yang ditulis di NFC tag serta dengan slug yang
    tercatat di database. Pada cetakan 30 mm itu berarti 0,73 mm per modul,
    masih jauh di atas ambang aman kamera HP (~0,4 mm).

    `compact=True` memangkas ke 29x29 (0,81 mm per modul di ukuran yang sama)
    dengan mengapitalkan scheme + domain. Slug tetap utuh. Pakai ini hanya
    kalau QR harus dicetak sangat kecil.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_Q,
        box_size=10,
        border=4,
        image_factory=SvgPathImage,
    )
    qr.add_data(compact_payload(url) if compact else url)
    qr.make(fit=True)
    return qr.make_image().to_string()


def make_qr_zip(pairs: Iterable[tuple[str, str]], *, compact: bool = False) -> bytes:
    """Satu ZIP berisi banyak QR SVG, dinamai per slug — untuk kirim ke percetakan.

    `pairs` berisi (slug, url). Sengaja hanya berisi file SVG: token aktivasi
    TIDAK boleh ikut ke percetakan, jadi tidak ada manifest berisi token di sini.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for slug, url in pairs:
            zf.writestr(f"{slug}.svg", make_qr_svg(url, compact=compact))
    return buf.getvalue()
