import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.database import get_session
from app.models import LinkStatus, ReviewLink
from app.schemas import normalize_url

router = APIRouter(prefix="/setup", tags=["setup"])

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

url_adapter = TypeAdapter(AnyHttpUrl)

# Satu pesan untuk semua kegagalan. Jangan bedakan "token salah" dari "sudah
# dipakai" — membedakannya membantu orang menebak token yang benar.
PESAN_INVALID = "Link aktivasi ini tidak valid atau sudah pernah dipakai."


def _boleh_aktivasi(link: ReviewLink | None, key: str | None) -> bool:
    """Dua syarat sekaligus: token cocok DAN status masih unassigned."""
    if link is None or not key or not link.activation_token:
        return False
    if not secrets.compare_digest(key, link.activation_token):
        return False
    return link.status == LinkStatus.UNASSIGNED


def _halaman_invalid(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "setup.html", {"state": "invalid"}, status_code=404
    )


@router.get("/{slug}", response_class=HTMLResponse, summary="Form aktivasi (publik, bertoken)")
async def show_form(
    slug: str,
    request: Request,
    key: str | None = Query(default=None, description="activation_token kartu"),
    session: AsyncSession = Depends(get_session),
):
    link = await crud.get_link(session, slug.lower())
    if not _boleh_aktivasi(link, key):
        return _halaman_invalid(request)
    return templates.TemplateResponse(
        request, "setup.html", {"state": "form", "slug": link.slug, "key": key}
    )


@router.post("/{slug}", response_class=HTMLResponse, summary="Submit form aktivasi")
async def submit_form(
    slug: str,
    request: Request,
    key: str = Form(...),
    business_name: str = Form(...),
    destination_url: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    link = await crud.get_link(session, slug.lower())
    if not _boleh_aktivasi(link, key):
        return _halaman_invalid(request)

    nama = business_name.strip()
    # Klien sering menempel link tanpa "https://" — lengkapi, jangan tolak.
    tujuan = normalize_url(destination_url)
    galat = None
    if not nama:
        galat = "Nama bisnis tidak boleh kosong."
    else:
        try:
            url_adapter.validate_python(tujuan)
        except ValidationError:
            galat = (
                "Link ulasan Google tidak dikenali. Salin ulang langsung dari "
                "Google, contohnya g.page/r/.../review"
            )

    if galat:
        return templates.TemplateResponse(
            request,
            "setup.html",
            {
                "state": "form",
                "slug": link.slug,
                "key": key,
                "error": galat,
                "business_name": nama,
                "destination_url": tujuan,
            },
            status_code=400,
        )

    await crud.activate_link(session, link, nama, tujuan)
    return templates.TemplateResponse(
        request,
        "setup.html",
        {"state": "success", "slug": link.slug, "business_name": nama},
    )
