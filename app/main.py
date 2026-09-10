from fastapi import FastAPI

from app.config import settings
from app.routers import admin, panel, redirect, setup

app = FastAPI(
    title="Nuku Review Redirect",
    description=(
        "Satu titik kontrol untuk semua link Google Review klien. "
        "Kartu dicetak massal sebagai stok polos, lalu diaktivasi per klien lewat link bertoken. QR/NFC mengarah ke /r/{slug}, tujuannya bisa diganti "
        "tanpa cetak ulang akrilik."
    ),
    version="2.0.0",
    docs_url="/admin/docs",
    redoc_url=None,
    openapi_url="/admin/openapi.json",
)

app.include_router(redirect.router)
app.include_router(setup.router)
app.include_router(panel.router)
app.include_router(admin.router)


@app.get("/health", tags=["public"], summary="Health check untuk monitoring")
async def health() -> dict:
    return {"status": "ok", "base_url": settings.public_base}
