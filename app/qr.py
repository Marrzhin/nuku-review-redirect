import io
import zipfile
from collections.abc import Iterable

import qrcode
from qrcode.image.svg import SvgPathImage


def make_qr_svg(url: str, *, upper: bool = True) -> bytes:
    """QR code format SVG (vector) — tetap tajam di ukuran cetak berapa pun.

    Error correction level Q: masih terbaca walau permukaan akrilik tergores
    atau sebagian tertutup, tanpa membuat modul terlalu rapat.

    `upper` meng-encode URL dalam huruf kapital supaya QR memakai mode
    alfanumerik, bukan mode byte. Hasilnya lebih sedikit modul untuk isi yang
    sama — mis. 29x29 dibanding 33x33 — sehingga tiap modul bisa dicetak lebih
    besar di akrilik berukuran sama, dan lebih tahan gores serta pantulan
    cahaya. Aman karena scheme dan domain memang case-insensitive, dan slug
    di-lowercase saat lookup di routers/redirect.py.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_Q,
        box_size=10,
        border=4,
        image_factory=SvgPathImage,
    )
    qr.add_data(url.upper() if upper else url)
    qr.make(fit=True)
    return qr.make_image().to_string()


def make_qr_zip(pairs: Iterable[tuple[str, str]], *, upper: bool = True) -> bytes:
    """Satu ZIP berisi banyak QR SVG, dinamai per slug — untuk kirim ke percetakan.

    `pairs` berisi (slug, url). Sengaja hanya berisi file SVG: token aktivasi
    TIDAK boleh ikut ke percetakan, jadi tidak ada manifest berisi token di sini.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for slug, url in pairs:
            zf.writestr(f"{slug}.svg", make_qr_svg(url, upper=upper))
    return buf.getvalue()
