import re
from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

from app.models import LinkStatus

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
BATCH_LABEL_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def normalize_slug(value: str) -> str:
    """Rapikan lalu validasi slug supaya URL-safe: huruf kecil, angka, strip."""
    slug = value.strip().lower()
    if not 3 <= len(slug) <= 64:
        raise ValueError("slug harus 3-64 karakter")
    if not SLUG_PATTERN.match(slug):
        raise ValueError(
            "slug hanya boleh huruf kecil, angka, dan strip di antaranya "
            "(contoh: warkop-sinar)"
        )
    return slug


class BatchCreate(BaseModel):
    """Fase 1 — cetak stok kartu polos, belum ada kliennya."""

    count: int = Field(ge=1, le=500, description="Jumlah kartu yang mau dicetak")
    batch_label: str | None = Field(
        default=None,
        description="Default: batch-YYYY-MM dari tanggal hari ini",
        max_length=32,
    )

    @field_validator("batch_label")
    @classmethod
    def _label(cls, v: str | None) -> str | None:
        if v is None:
            return None
        label = v.strip().lower()
        if not 3 <= len(label) <= 32 or not BATCH_LABEL_PATTERN.match(label):
            raise ValueError(
                "batch_label hanya boleh huruf kecil, angka, dan strip "
                "(contoh: batch-2026-09)"
            )
        return label


class BatchItem(BaseModel):
    """Satu kartu hasil produksi. `setup_url` dikirim privat saat closing."""

    slug: str
    activation_token: str
    redirect_url: str
    setup_url: str


class BatchOut(BaseModel):
    batch_label: str
    count: int
    items: list[BatchItem]


class LinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    status: LinkStatus
    batch_label: str
    business_name: str | None
    destination_url: str | None
    created_at: datetime
    activated_at: datetime | None
    updated_at: datetime


class LinkDetail(LinkOut):
    """Detail untuk admin — memuat token supaya link aktivasi bisa dikirim ulang."""

    redirect_url: str
    activation_token: str | None
    setup_url: str | None


class LinkUpdate(BaseModel):
    """Semua opsional — hanya field yang dikirim yang diubah."""

    business_name: str | None = Field(default=None, min_length=1, max_length=255)
    destination_url: AnyHttpUrl | None = None
    status: LinkStatus | None = None


class LinkStats(BaseModel):
    slug: str
    business_name: str | None
    status: LinkStatus
    total_hits: int
    hits_last_7_days: int
    last_hit_at: datetime | None


class PlaceLookupRequest(BaseModel):
    business_name: str = Field(min_length=1, max_length=255)
    full_address: str = Field(min_length=1, max_length=500)


class PlaceCandidate(BaseModel):
    place_id: str
    display_name: str | None = None
    formatted_address: str | None = None
    suggested_destination_url: str = Field(
        description="Format Maps resmi — terbuka tanpa login. Pakai ini."
    )
    writereview_url: str = Field(
        description="Langsung ke kotak ulasan, TAPI mewajibkan login Google. "
        "Bisa gagal (ERR_TOO_MANY_REDIRECTS) di browser tertentu."
    )


class PlaceLookupResponse(BaseModel):
    result: str = Field(description="found | ambiguous | not_found")
    message: str
    place_id: str | None = None
    suggested_destination_url: str | None = Field(
        default=None, description="Format Maps resmi — terbuka tanpa login. Pakai ini."
    )
    writereview_url: str | None = Field(
        default=None,
        description="Langsung ke kotak ulasan, TAPI mewajibkan login Google. "
        "Bisa gagal (ERR_TOO_MANY_REDIRECTS) di browser tertentu.",
    )
    candidates: list[PlaceCandidate] = []
