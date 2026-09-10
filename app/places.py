"""Lookup Place ID lewat Places API (New) — Text Search.

Aturan biaya yang dijaga di sini: panggilan pertama memakai field mask
`places.id` saja, yang masuk tier "IDs Only" dan tidak ditagih berapa pun
volumenya. Menambah field lain memindahkan SELURUH request ke tier berbayar,
bukan cuma field tambahannya — jadi mask yang lebih lengkap hanya dipakai di
satu kasus: saat hasilnya ambigu dan admin butuh melihat nama + alamat untuk
memilih. Lihat bagian "Integrasi Google Places API" di blueprint.
"""

from urllib.parse import quote

import httpx

from app.config import settings
from app.schemas import PlaceCandidate, PlaceLookupResponse

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
MASK_GRATIS = "places.id"
MASK_AMBIGU = "places.id,places.displayName,places.formattedAddress"
MAKS_KANDIDAT = 5
TIMEOUT = httpx.Timeout(10.0)


class PlacesNotConfigured(RuntimeError):
    pass


class PlacesError(RuntimeError):
    pass


def maps_url(place_id: str, nama: str | None = None) -> str:
    """Link tujuan yang disarankan — format Google Maps URLs resmi (api=1).

    Dipilih karena terbuka tanpa login: pelanggan yang scan kartu di kafe belum
    tentu sedang masuk akun Google, terutama di iPhone. Di HP, link ini membuka
    aplikasi Maps tempat mereka sudah masuk, lalu tinggal tekan "Tulis ulasan".
    """
    q = quote(nama or "", safe="")
    return (
        f"https://www.google.com/maps/search/?api=1&query={q}"
        f"&query_place_id={place_id}"
    )


def writereview_url(place_id: str) -> str:
    """Alternatif yang langsung membuka kotak ulasan — TAPI mewajibkan login.

    Kalau pengunjung belum masuk akun Google, link ini melempar ke
    accounts.google.com, dan pada browser dengan cookie pihak ketiga diblokir
    atau banyak akun tertaut, bisa berakhir ERR_TOO_MANY_REDIRECTS. Jangan
    dijadikan tujuan default kartu; pakai hanya kalau kondisi kliennya
    memang terkendali.
    """
    return f"https://search.google.com/local/writereview?placeid={place_id}"


async def _search(client: httpx.AsyncClient, query: str, mask: str) -> list[dict]:
    r = await client.post(
        SEARCH_URL,
        json={"textQuery": query},
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": settings.google_places_api_key,
            "X-Goog-FieldMask": mask,
        },
    )
    if r.status_code != 200:
        raise PlacesError(f"Places API balas {r.status_code}: {r.text[:300]}")
    return r.json().get("places", [])


async def lookup_place(business_name: str, full_address: str) -> PlaceLookupResponse:
    if not settings.google_places_api_key:
        raise PlacesNotConfigured("GOOGLE_PLACES_API_KEY belum diset di server.")

    query = f"{business_name} {full_address}".strip()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            hasil = await _search(client, query, MASK_GRATIS)
        except httpx.HTTPError as e:
            raise PlacesError(f"Gagal menghubungi Places API: {e}") from e

        if not hasil:
            return PlaceLookupResponse(
                result="not_found",
                message=(
                    "Tidak ada tempat yang cocok. Isi Place ID manual lewat "
                    "Place ID Finder, lalu pakai PATCH /admin/links/{slug}."
                ),
            )

        if len(hasil) == 1:
            place_id = hasil[0]["id"]
            return PlaceLookupResponse(
                result="found",
                message="Ketemu satu tempat.",
                place_id=place_id,
                suggested_destination_url=maps_url(place_id, business_name),
                writereview_url=writereview_url(place_id),
            )

        # Ambigu: baru di sini mask diperlebar, dan hanya sekali.
        try:
            rinci = await _search(client, query, MASK_AMBIGU)
        except (httpx.HTTPError, PlacesError):
            rinci = hasil  # tetap kembalikan ID-nya walau detail gagal diambil

    kandidat = []
    for p in rinci[:MAKS_KANDIDAT]:
        nama = (p.get("displayName") or {}).get("text")
        kandidat.append(
            PlaceCandidate(
                place_id=p["id"],
                display_name=nama,
                formatted_address=p.get("formattedAddress"),
                suggested_destination_url=maps_url(p["id"], nama or business_name),
                writereview_url=writereview_url(p["id"]),
            )
        )
    return PlaceLookupResponse(
        result="ambiguous",
        message=(
            f"Ada {len(hasil)} tempat yang cocok — pilih salah satu, "
            "atau persempit alamatnya lalu ulangi."
        ),
        candidates=kandidat,
    )
