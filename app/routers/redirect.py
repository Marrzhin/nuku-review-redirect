from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.config import settings
from app.database import SessionLocal, get_session
from app.models import LinkStatus
from app.schemas import SLUG_PATTERN

router = APIRouter(tags=["public"])

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


def _fallback(request: Request, slug: str) -> HTMLResponse:
    """Halaman untuk kartu yang belum/tidak aktif.

    Isinya sama persis untuk slug tak dikenal, `unassigned`, dan `inactive` —
    jangan bedakan, supaya tidak membocorkan status kartu ke orang luar.

    Kode kartu hanya diteruskan ke link WhatsApp kalau bentuknya memang slug
    yang sah; segala isian aneh dari URL tidak ikut masuk ke pesan.
    """
    kode = slug.lower() if SLUG_PATTERN.match(slug.lower()) else None
    # 200, bukan 404: pelanggan yang scan QR tidak perlu lihat error mentah.
    return templates.TemplateResponse(
        request,
        "fallback.html",
        {
            "pesan": settings.fallback_contact,
            "kode": kode,
            "wa_url": settings.whatsapp_url(kode),
        },
        status_code=200,
        headers={"Cache-Control": "no-store"},
    )


async def _log_hit(link_id: int, user_agent: str | None) -> None:
    """Dijalankan setelah response terkirim, pakai session sendiri.

    Gagal mencatat hit tidak boleh mengganggu redirect pelanggan.
    """
    try:
        async with SessionLocal() as session:
            await crud.record_hit(session, link_id, user_agent)
    except Exception:  # noqa: BLE001 - analytics bersifat best-effort
        pass


@router.get("/r/{slug}", summary="Redirect publik ke Google Review")
async def redirect_to_review(
    slug: str,
    request: Request,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    # Rute ini tidak pernah membaca parameter `key` — logika token hanya ada di
    # /setup. Di sini murni cek status, supaya kartu yang ditemukan orang lain
    # tidak pernah jadi pintu masuk ke form aktivasi.
    link = await crud.get_link(session, slug.lower())
    if link is None or link.status != LinkStatus.ACTIVE or not link.destination_url:
        return _fallback(request, slug)

    background.add_task(_log_hit, link.id, request.headers.get("user-agent"))
    # 302, bukan 301: update destination_url harus langsung berlaku,
    # tanpa tersangkut cache permanen di browser/aplikasi scanner.
    return RedirectResponse(
        link.destination_url,
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )
