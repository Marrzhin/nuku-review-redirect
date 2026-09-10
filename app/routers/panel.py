from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["admin"])

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


@router.get(
    "/admin/panel",
    response_class=HTMLResponse,
    include_in_schema=False,
    summary="Panel kerja admin",
)
async def panel(request: Request):
    """Halaman kerja admin.

    Sengaja TIDAK dilindungi require_admin: browser tidak bisa mengirim header
    X-Admin-Key saat URL diketik biasa. Yang dikirim di sini hanya kerangka
    halaman tanpa data sedikit pun — seluruh isinya diambil lewat fetch() oleh
    JavaScript, yang barulah menyertakan header itu. Jadi gerbang tetap ada di
    endpoint /admin/* yang membawa data, bukan di halaman ini.
    """
    return templates.TemplateResponse(request, "panel.html", {})
