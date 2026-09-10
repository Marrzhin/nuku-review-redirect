import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud, places
from app.config import settings
from app.database import get_session
from app.models import LinkStatus, ReviewLink
from app.qr import make_qr_svg, make_qr_zip
from app.schemas import (
    BatchCreate,
    BatchItem,
    BatchOut,
    LinkDetail,
    LinkOut,
    LinkStats,
    LinkUpdate,
    PlaceLookupRequest,
    PlaceLookupResponse,
)

api_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


async def require_admin(key: str | None = Depends(api_key_header)) -> None:
    if not settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_API_KEY belum diset di server.",
        )
    if not key or not secrets.compare_digest(key, settings.admin_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin key tidak valid."
        )


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _detail(link: ReviewLink) -> LinkDetail:
    masih_stok = link.status == LinkStatus.UNASSIGNED and link.activation_token
    return LinkDetail(
        **LinkOut.model_validate(link).model_dump(),
        redirect_url=settings.redirect_url(link.slug),
        activation_token=link.activation_token,
        # Link aktivasi hanya berarti selama kartu masih unassigned; setelah
        # aktif, rutenya memang sudah tertutup sendiri.
        setup_url=(
            settings.setup_url(link.slug, link.activation_token) if masih_stok else None
        ),
    )


async def _get_or_404(session: AsyncSession, slug: str) -> ReviewLink:
    link = await crud.get_link(session, slug.lower())
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Slug '{slug}' tidak ada."
        )
    return link


# --- Fase 1: produksi stok kartu -------------------------------------------


@router.post(
    "/slugs/batch",
    response_model=BatchOut,
    status_code=status.HTTP_201_CREATED,
    summary="Generate N kartu polos untuk satu batch produksi",
)
async def create_batch(
    payload: BatchCreate, session: AsyncSession = Depends(get_session)
):
    label = payload.batch_label or crud.default_batch_label()
    try:
        links = await crud.create_batch(session, payload.count, label)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e
    return BatchOut(
        batch_label=label,
        count=len(links),
        items=[
            BatchItem(
                slug=link.slug,
                activation_token=link.activation_token,
                redirect_url=settings.redirect_url(link.slug),
                setup_url=settings.setup_url(link.slug, link.activation_token),
            )
            for link in links
        ],
    )


@router.get(
    "/qr/export",
    response_class=Response,
    summary="ZIP berisi semua QR SVG yang cocok filter",
)
async def export_qr(
    batch_label: str | None = Query(default=None, description="mis. batch-2026-09"),
    link_status: LinkStatus | None = Query(
        default=None, alias="status", description="Filter status kartu"
    ),
    compact: bool = Query(
        default=False,
        description="Padatkan QR ke 29x29 dengan mengapitalkan domain "
        "(slug tetap utuh). Default 33x33, isi QR sama persis dengan URL "
        "yang ditulis di NFC tag.",
    ),
    session: AsyncSession = Depends(get_session),
):
    links = await crud.list_links(session, status=link_status, batch_label=batch_label)
    if not links:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tidak ada kartu yang cocok dengan filter itu.",
        )
    blob = make_qr_zip(
        ((link.slug, settings.redirect_url(link.slug)) for link in links),
        compact=compact,
    )
    nama = (batch_label.strip().lower() if batch_label else None) or (
        link_status.value if link_status else "semua"
    )
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="qr-{nama}.zip"'},
    )


# --- Kelola link ------------------------------------------------------------


@router.get("/links", response_model=list[LinkOut], summary="List semua kartu")
async def list_links(
    link_status: LinkStatus | None = Query(
        default=None, alias="status", description="Filter status kartu"
    ),
    batch_label: str | None = Query(default=None, description="Filter batch produksi"),
    session: AsyncSession = Depends(get_session),
):
    return await crud.list_links(session, status=link_status, batch_label=batch_label)


@router.get("/links/{slug}", response_model=LinkDetail, summary="Detail satu kartu")
async def get_link(slug: str, session: AsyncSession = Depends(get_session)):
    return _detail(await _get_or_404(session, slug))


@router.patch("/links/{slug}", response_model=LinkDetail, summary="Update kartu")
async def update_link(
    slug: str, payload: LinkUpdate, session: AsyncSession = Depends(get_session)
):
    # Catatan: slug tidak bisa diubah — sudah tercetak di akrilik klien.
    link = await _get_or_404(session, slug)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidak ada field yang diubah.",
        )
    if data.get("status") == LinkStatus.ACTIVE and not (
        data.get("destination_url") or link.destination_url
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidak bisa set status=active tanpa destination_url.",
        )
    return _detail(await crud.update_link(session, link, payload))


@router.get("/links/{slug}/qr", response_class=Response, summary="QR SVG satu kartu")
async def get_qr(
    slug: str,
    download: bool = Query(default=True, description="Kirim sebagai file download"),
    compact: bool = Query(
        default=False,
        description="Padatkan QR ke 29x29 dengan mengapitalkan domain "
        "(slug tetap utuh). Default 33x33, isi QR sama persis dengan URL "
        "yang ditulis di NFC tag.",
    ),
    session: AsyncSession = Depends(get_session),
):
    link = await _get_or_404(session, slug)
    svg = make_qr_svg(settings.redirect_url(link.slug), compact=compact)
    disposition = "attachment" if download else "inline"
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Content-Disposition": f'{disposition}; filename="qr-{link.slug}.svg"'
        },
    )


@router.get("/links/{slug}/stats", response_model=LinkStats, summary="Statistik hit")
async def get_stats(slug: str, session: AsyncSession = Depends(get_session)):
    link = await _get_or_404(session, slug)
    return await crud.get_stats(session, link)


# --- Google Places ----------------------------------------------------------


@router.post(
    "/lookup-place",
    response_model=PlaceLookupResponse,
    summary="Cari Place ID lewat Places API (New)",
)
async def lookup_place(payload: PlaceLookupRequest):
    try:
        return await places.lookup_place(payload.business_name, payload.full_address)
    except places.PlacesNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from e
    except places.PlacesError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)
        ) from e
