import secrets
from datetime import date, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LinkStatus, RedirectHit, ReviewLink, utcnow
from app.schemas import LinkUpdate

# Tanpa 0/1/i/l/o supaya slug tidak ambigu kalau sewaktu-waktu dibaca manusia
# dari cetakan atau didikte lewat telepon.
SLUG_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
SLUG_LENGTH = 8


def new_slug() -> str:
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(SLUG_LENGTH))


def new_activation_token() -> str:
    return secrets.token_urlsafe(16)


def default_batch_label(today: date | None = None) -> str:
    return f"batch-{(today or date.today()):%Y-%m}"


async def get_link(session: AsyncSession, slug: str) -> ReviewLink | None:
    result = await session.execute(select(ReviewLink).where(ReviewLink.slug == slug))
    return result.scalar_one_or_none()


async def list_links(
    session: AsyncSession,
    *,
    status: LinkStatus | None = None,
    batch_label: str | None = None,
) -> list[ReviewLink]:
    stmt = select(ReviewLink).order_by(ReviewLink.created_at.desc(), ReviewLink.id.desc())
    if status is not None:
        stmt = stmt.where(ReviewLink.status == status)
    if batch_label is not None:
        # Dinormalisasi supaya hasilnya sama di MariaDB (collation ..._ci,
        # cocok tanpa peduli huruf besar/kecil) dan SQLite (case-sensitive).
        stmt = stmt.where(ReviewLink.batch_label == batch_label.strip().lower())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_batch(
    session: AsyncSession, count: int, batch_label: str
) -> list[ReviewLink]:
    """Fase 1: bikin N kartu polos sekaligus, status unassigned.

    Slug diacak, jadi tabrakan mungkin terjadi walau kecil kemungkinannya.
    Kandidat dicek ke database dalam satu query per putaran, bukan satu per slug.
    """
    terpilih: set[str] = set()
    for _ in range(20):  # batas putaran, supaya tidak pernah jadi loop tak berujung
        kurang = count - len(terpilih)
        if kurang <= 0:
            break
        kandidat = {new_slug() for _ in range(kurang * 2)} - terpilih
        if not kandidat:
            continue
        result = await session.execute(
            select(ReviewLink.slug).where(ReviewLink.slug.in_(kandidat))
        )
        dipakai = set(result.scalars().all())
        terpilih.update(list(kandidat - dipakai)[:kurang])

    if len(terpilih) < count:
        raise RuntimeError(
            "gagal membuat slug unik yang cukup — coba lagi atau perpanjang SLUG_LENGTH"
        )

    links = [
        ReviewLink(
            slug=slug,
            status=LinkStatus.UNASSIGNED,
            activation_token=new_activation_token(),
            batch_label=batch_label,
        )
        for slug in sorted(terpilih)
    ]
    session.add_all(links)
    await session.commit()
    for link in links:
        await session.refresh(link)
    return links


async def update_link(
    session: AsyncSession, link: ReviewLink, payload: LinkUpdate
) -> ReviewLink:
    data = payload.model_dump(exclude_unset=True)
    if data.get("destination_url") is not None:
        data["destination_url"] = str(data["destination_url"])

    status_baru = data.get("status")
    if status_baru == LinkStatus.ACTIVE and link.activated_at is None:
        # Jejak kapan kartu pertama kali hidup, walau diaktifkan lewat admin.
        link.activated_at = utcnow()

    for field, value in data.items():
        setattr(link, field, value)
    await session.commit()
    await session.refresh(link)
    return link


async def activate_link(
    session: AsyncSession, link: ReviewLink, business_name: str, destination_url: str
) -> ReviewLink:
    """Fase 2: dipanggil dari form publik /setup, setelah token & status divalidasi."""
    link.business_name = business_name
    link.destination_url = destination_url
    link.status = LinkStatus.ACTIVE
    link.activated_at = utcnow()
    await session.commit()
    await session.refresh(link)
    return link


async def record_hit(
    session: AsyncSession, link_id: int, user_agent: str | None
) -> None:
    session.add(
        RedirectHit(
            link_id=link_id,
            user_agent=user_agent[:255] if user_agent else None,
        )
    )
    await session.commit()


async def get_stats(session: AsyncSession, link: ReviewLink) -> dict:
    since = utcnow() - timedelta(days=7)
    result = await session.execute(
        select(
            func.count(RedirectHit.id),
            func.sum(case((RedirectHit.hit_at >= since, 1), else_=0)),
            func.max(RedirectHit.hit_at),
        ).where(RedirectHit.link_id == link.id)
    )
    total, last_7, last_hit = result.one()
    return {
        "slug": link.slug,
        "business_name": link.business_name,
        "status": link.status,
        "total_hits": int(total or 0),
        "hits_last_7_days": int(last_7 or 0),
        "last_hit_at": last_hit,
    }
