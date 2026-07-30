from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters.is_admin import IsAdmin
from app.keyboards.admin_kb import ADMIN_BTN_STATS
from app.services.stats_service import StatsService
from app.utils.formatting import fmt_price

router = Router(name="admin_stats")
router.message.filter(IsAdmin())


def _render(stats) -> str:
    most_sold = (
        "\n".join(f"  {i+1}. {name} — {count} ta" for i, (name, count) in enumerate(stats.most_sold))
        or "  -"
    )
    return (
        "\U0001F4CA <b>Statistika</b>\n\n"
        f"\U0001F465 Foydalanuvchilar: {stats.total_users}\n"
        f"\U0001F6CD️ Mahsulotlar: {stats.total_products}\n"
        f"\U0001F4E6 Jami buyurtmalar: {stats.total_orders}\n"
        f"⏳ Kutilayotgan: {stats.pending_orders}\n"
        f"✅ Tasdiqlangan: {stats.approved_orders}\n"
        f"❌ Rad etilgan: {stats.rejected_orders}\n"
        f"\U0001F4E4 Yetkazilgan: {stats.delivered_orders}\n"
        f"\U0001F4B0 Jami savdo: {fmt_price(stats.total_sales)}\n\n"
        f"\U0001F3C6 Eng ko'p sotilganlar:\n{most_sold}"
    )


@router.message(F.text == ADMIN_BTN_STATS)
async def show_stats(message: Message, session: AsyncSession) -> None:
    stats = await StatsService(session).collect()
    await message.answer(_render(stats))
