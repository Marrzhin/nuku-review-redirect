from functools import lru_cache
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Konfigurasi dibaca dari environment / file .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./dev.db"
    admin_api_key: str = ""
    base_url: str = "https://go.nukustudio.id"

    # Dipakai run.py saat dijalankan systemd di VPS.
    port: int = 8000
    debug: bool = False

    # Places API (New). Kosong = endpoint /admin/lookup-place balas 503.
    google_places_api_key: str = ""

    # Nomor WhatsApp di halaman "kartu belum aktif". Format internasional
    # tanpa tanda + dan tanpa nol di depan: 62812xxxxxxx.
    # Kosongkan untuk menyembunyikan tombolnya.
    whatsapp_number: str = "6282394707711"

    # Ditampilkan di halaman fallback saat link nonaktif / tidak ditemukan.
    fallback_contact: str = "Kartu ini belum terhubung ke halaman ulasan mana pun."

    @property
    def public_base(self) -> str:
        return self.base_url.rstrip("/")

    def redirect_url(self, slug: str) -> str:
        """URL yang tercetak di QR/NFC. Tidak pernah membawa token."""
        return f"{self.public_base}/r/{slug}"

    def setup_url(self, slug: str, token: str) -> str:
        """Link aktivasi privat — dikirim ke klien lewat WA/japri, bukan dicetak."""
        return f"{self.public_base}/setup/{slug}?key={token}"

    def whatsapp_url(self, kode: str | None = None) -> str:
        """Link WhatsApp untuk halaman "kartu belum aktif".

        Kode kartu ikut di pesan awal supaya penerima tidak perlu bertanya
        "kartu yang mana" — orang yang menghubungi biasanya sedang memegang
        kartunya dan tidak tahu istilah "slug".
        """
        if not self.whatsapp_number:
            return ""
        pesan = "Halo Nuku Creative Studio, saya mau menanyakan kartu ulasan Google."
        if kode:
            pesan += f" Kode kartu: {kode}"
        return f"https://wa.me/{self.whatsapp_number}?text={quote(pesan)}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
