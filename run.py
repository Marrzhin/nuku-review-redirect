"""Entry point untuk systemd di VPS.

Unit `go-nukustudio.service` memanggil file ini lewat
`venv/bin/python3 run.py`, bukan `uvicorn` langsung. Host dikunci ke
127.0.0.1 — akses publik hanya lewat Nginx.
"""

import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=settings.port,
        # Nginx meneruskan X-Forwarded-Proto; tanpa ini uvicorn mengira
        # semua request datang sebagai HTTP.
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        log_level="debug" if settings.debug else "info",
    )
