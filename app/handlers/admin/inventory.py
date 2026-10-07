from __future__ import annotations

import io
from html import escape as html_escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters.is_admin import IsAdmin
from app.keyboards.admin_kb import (
    admin_inventory_menu_kb,
    admin_product_detail_kb,
    admin_stock_waiters_kb,
    inventory_delete_confirm_kb,
    inventory_delete_pick_kb,
)
from app.keyboards.callback_data import AdminInventoryCB, AdminStockWaitersCB
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.stock_waiter_repo import StockWaiterRepository
from app.services.stock_notify_service import notify_all_waiters
from app.states.admin_states import AdminInput
from app.utils.formatting import fmt_datetime
from app.utils.screen import show

router = Router(name="admin_inventory")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def _inventory_summary(session: AsyncSession, product_id: int) -> str:
    """Splits "unused" into what customers can actually buy vs. what's held
    by a pending order — the old single "unused" number counted both, so
    the panel could say 4 while customers saw the product as sold out."""
    free, reserved, used = await InventoryRepository(session).count_breakdown(product_id)
    lines = [
        "\U0001F4E6 <b>Inventar</b>",
        "",
        f"\U0001F7E2 Sotuvda (mijozlar ko'radi): <b>{free}</b>",
        f"\U0001F512 Band (to'lanayotgan buyurtmalarga ajratilgan): <b>{reserved}</b>",
        f"✅ Sotilgan (yetkazilgan): <b>{used}</b>",
    ]
    if reserved:
        lines += [
            "",
            "ℹ️ Band kodlar mijozga hali yuborilmagan. Ular to'lov kutilayotgan yoki tasdiqlanishi "
            "kerak bo'lgan buyurtmalarga ajratilgan — \U0001F512 tugmasi orqali qaysi buyurtmalar "
            "ekanini ko'ring.",
        ]
    return "\n".join(lines)


@router.callback_query(AdminInventoryCB.filter(F.action == "menu"))
async def inventory_menu(callback: CallbackQuery, callback_data: AdminInventoryCB, session: AsyncSession) -> None:
    await callback.message.edit_text(
        await _inventory_summary(session, callback_data.product_id),
        reply_markup=admin_inventory_menu_kb(callback_data.product_id),
    )
    await callback.answer()


_HOLDER_STATUS_LABELS = {
    "awaiting_proof": "chek kutilmoqda (mijoz hali chek yubormagan)",
    "awaiting_card_payment": "karta to'lovi kutilmoqda",
    "awaiting_crypto_payment": "kripto to'lov kutilmoqda",
    "awaiting_stars_payment": "Stars to'lov kutilmoqda",
    "pending_approval": "⚠️ chek yuborilgan — SIZNING tasdig'ingiz kutilmoqda",
    "approved": "⚠️ tasdiqlangan, lekin yetkazilmagan",
}


@router.callback_query(AdminInventoryCB.filter(F.action == "reserved"))
async def inventory_reserved(callback: CallbackQuery, callback_data: AdminInventoryCB, session: AsyncSession) -> None:
    rows = await InventoryRepository(session).list_reserved_with_orders(callback_data.product_id)
    if not rows:
        await callback.answer("Band kodlar yo'q — hammasi sotuvda.", show_alert=True)
        return
    lines = [f"\U0001F512 <b>Band kodlar ({len(rows)})</b>", ""]
    for code, order in rows[:30]:
        if order is None:
            lines.append(f"• <code>{html_escape(code.code[:40])}</code> — buyurtma topilmadi (avtomatik bo'shatiladi)")
            continue
        status = _HOLDER_STATUS_LABELS.get(order.status.value, order.status.value)
        lines.append(
            f"• <code>{order.order_uuid}</code> — {status}\n"
            f"   \U0001F4C5 {fmt_datetime(order.created_at)}"
        )
    if len(rows) > 30:
        lines.append(f"\n... va yana {len(rows) - 30} ta")
    lines += [
        "",
        "Buyurtma ID'sini Buyurtmalar → ID bo'yicha qidirish orqali ochib, tasdiqlang yoki rad eting. "
        "Chek yubormagan mijozlarning kodlari 1 soatdan keyin avtomatik sotuvga qaytadi; tugagan "
        "(bekor/rad) buyurtmalardagi kodlar esa darhol qaytadi.",
    ]
    await show(callback, "\n".join(lines), reply_markup=admin_inventory_menu_kb(callback_data.product_id))
    await callback.answer()


@router.callback_query(AdminInventoryCB.filter(F.action == "add_one"))
async def inventory_add_one(callback: CallbackQuery, callback_data: AdminInventoryCB, state: FSMContext) -> None:
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(panel_chat_id=callback.message.chat.id, panel_message_id=callback.message.message_id, action="inventory_add_one", product_id=callback_data.product_id)
    await show(callback, "Yangi kodni yozing (bitta):")
    await callback.answer()


@router.callback_query(AdminInventoryCB.filter(F.action == "bulk"))
async def inventory_bulk_start(callback: CallbackQuery, callback_data: AdminInventoryCB, state: FSMContext) -> None:
    await state.set_state(AdminInput.waiting_codes_file_or_text)
    await state.update_data(panel_chat_id=callback.message.chat.id, panel_message_id=callback.message.message_id, action="inventory_bulk", product_id=callback_data.product_id)
    await show(callback, 
        "Kodlarni yuboring — har bir qatorda bitta kod (matn sifatida yozing yoki .txt fayl yuboring)."
    )
    await callback.answer()


@router.callback_query(AdminStockWaitersCB.filter(F.action == "list"))
async def stock_waiters_list(callback: CallbackQuery, callback_data: AdminStockWaitersCB, session: AsyncSession) -> None:
    waiters = await StockWaiterRepository(session).list_waiting(callback_data.product_id)
    if not waiters:
        await callback.message.edit_text(
            "\U0001F514 Hozircha bu mahsulotni hech kim kutmayapti.",
            reply_markup=admin_stock_waiters_kb(callback_data.product_id, has_waiters=False),
        )
        await callback.answer()
        return
    lines = [
        f"\U0001F464 @{w.user.username or '-'} ({w.user.telegram_id})" for w in waiters
    ]
    text = f"\U0001F514 Kutayotganlar ({len(waiters)} ta):\n\n" + "\n".join(lines[:50])
    if len(waiters) > 50:
        text += f"\n... va yana {len(waiters) - 50} ta"
    await callback.message.edit_text(text, reply_markup=admin_stock_waiters_kb(callback_data.product_id, has_waiters=True))
    await callback.answer()


@router.callback_query(AdminStockWaitersCB.filter(F.action == "notify_all"))
async def stock_waiters_notify_all(
    callback: CallbackQuery, callback_data: AdminStockWaitersCB, session: AsyncSession
) -> None:
    product = await ProductRepository(session).get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    count = await notify_all_waiters(session, callback.bot, product)
    await callback.message.edit_text(
        f"✅ {count} ta foydalanuvchiga xabar berildi.",
        reply_markup=admin_stock_waiters_kb(callback_data.product_id, has_waiters=False),
    )
    await callback.answer()


@router.callback_query(AdminInventoryCB.filter(F.action == "view"))
async def inventory_view(callback: CallbackQuery, callback_data: AdminInventoryCB, session: AsyncSession) -> None:
    codes = await InventoryRepository(session).list_codes(callback_data.product_id, only_unused=True)
    if not codes:
        await callback.answer("Ishlatilmagan kodlar yo'q", show_alert=True)
        return
    preview = "\n".join(
        html_escape(c.code) + ("   \U0001F512 band" if c.is_reserved else "") for c in codes[:30]
    )
    more = f"\n... va yana {len(codes) - 30} ta" if len(codes) > 30 else ""
    await show(
        callback,
        f"\U0001F4CB Ishlatilmagan kodlar ({len(codes)}):\n"
        f"\U0001F512 belgisi — buyurtmaga ajratilgan, mijozlarga sotuvda ko'rinmaydi.\n\n"
        f"<code>{preview}</code>{more}",
    )
    await callback.answer()


def _selected_key(product_id: int) -> str:
    # FSM data is per-user, but an admin could have multiple products' delete
    # pickers open across different chats/messages in principle — namespace
    # the selection by product to keep them from bleeding into each other.
    return f"inv_selected_{product_id}"


async def _get_selected(state: FSMContext, product_id: int) -> set[int]:
    data = await state.get_data()
    return set(data.get(_selected_key(product_id), []))


@router.callback_query(AdminInventoryCB.filter(F.action == "pick_delete"))
async def inventory_pick_delete(
    callback: CallbackQuery, callback_data: AdminInventoryCB, session: AsyncSession, state: FSMContext
) -> None:
    codes = await InventoryRepository(session).list_codes(callback_data.product_id, only_unused=True)
    if not codes:
        await callback.answer("Ishlatilmagan kodlar yo'q", show_alert=True)
        return
    await state.update_data(**{_selected_key(callback_data.product_id): []})
    # Telegram inline keyboards get unwieldy past ~50 buttons — show the
    # oldest 50 unused codes at a time, same soft cap as view/export.
    await callback.message.edit_text(
        f"\U0001F5D1️ O'chirish uchun kod(lar)ni belgilang ({len(codes)} ta ishlatilmagan):",
        reply_markup=inventory_delete_pick_kb(callback_data.product_id, codes[:50]),
    )
    await callback.answer()


@router.callback_query(AdminInventoryCB.filter(F.action == "toggle_select"))
async def inventory_toggle_select(
    callback: CallbackQuery, callback_data: AdminInventoryCB, session: AsyncSession, state: FSMContext
) -> None:
    selected = await _get_selected(state, callback_data.product_id)
    if callback_data.code_id in selected:
        selected.remove(callback_data.code_id)
    else:
        selected.add(callback_data.code_id)
    await state.update_data(**{_selected_key(callback_data.product_id): list(selected)})

    codes = await InventoryRepository(session).list_codes(callback_data.product_id, only_unused=True)
    await callback.message.edit_reply_markup(
        reply_markup=inventory_delete_pick_kb(callback_data.product_id, codes[:50], selected)
    )
    await callback.answer()


@router.callback_query(AdminInventoryCB.filter(F.action == "delete_selected"))
async def inventory_delete_selected_confirm(
    callback: CallbackQuery, callback_data: AdminInventoryCB, state: FSMContext
) -> None:
    selected = await _get_selected(state, callback_data.product_id)
    if not selected:
        await callback.answer("Hech narsa belgilanmagan", show_alert=True)
        return
    await callback.message.edit_text(
        f"{len(selected)} ta belgilangan kodni o'chirmoqchimisiz?",
        reply_markup=inventory_delete_confirm_kb(callback_data.product_id, "confirm_selected"),
    )
    await callback.answer()


@router.callback_query(AdminInventoryCB.filter(F.action == "confirm_selected"))
async def inventory_confirm_delete_selected(
    callback: CallbackQuery, callback_data: AdminInventoryCB, session: AsyncSession, state: FSMContext
) -> None:
    selected = await _get_selected(state, callback_data.product_id)
    count = await InventoryRepository(session).delete_codes(list(selected))
    await state.update_data(**{_selected_key(callback_data.product_id): []})
    await callback.answer(f"✅ {count} ta kod o'chirildi")
    await callback.message.edit_text(
        await _inventory_summary(session, callback_data.product_id),
        reply_markup=admin_inventory_menu_kb(callback_data.product_id),
    )


@router.callback_query(AdminInventoryCB.filter(F.action == "delete_all"))
async def inventory_delete_all_confirm(
    callback: CallbackQuery, callback_data: AdminInventoryCB, session: AsyncSession
) -> None:
    unused = await InventoryRepository(session).count_unused(callback_data.product_id)
    if not unused:
        await callback.answer("Ishlatilmagan kodlar yo'q", show_alert=True)
        return
    await callback.message.edit_text(
        f"⚠️ Barcha {unused} ta ishlatilmagan kodni o'chirmoqchimisiz? Bu qaytarib bo'lmaydi.",
        reply_markup=inventory_delete_confirm_kb(callback_data.product_id, "confirm_all"),
    )
    await callback.answer()


@router.callback_query(AdminInventoryCB.filter(F.action == "confirm_all"))
async def inventory_confirm_delete_all(
    callback: CallbackQuery, callback_data: AdminInventoryCB, session: AsyncSession, state: FSMContext
) -> None:
    count = await InventoryRepository(session).delete_all_unused(callback_data.product_id)
    await state.update_data(**{_selected_key(callback_data.product_id): []})
    await callback.answer(f"✅ {count} ta kod o'chirildi")
    await callback.message.edit_text(
        await _inventory_summary(session, callback_data.product_id),
        reply_markup=admin_inventory_menu_kb(callback_data.product_id),
    )


@router.callback_query(AdminInventoryCB.filter(F.action == "export"))
async def inventory_export(callback: CallbackQuery, callback_data: AdminInventoryCB, session: AsyncSession) -> None:
    codes = await InventoryRepository(session).list_codes(callback_data.product_id, only_unused=True)
    if not codes:
        await callback.answer("Ishlatilmagan kodlar yo'q", show_alert=True)
        return
    content = "\n".join(c.code for c in codes).encode("utf-8")
    file = BufferedInputFile(content, filename=f"product_{callback_data.product_id}_codes.txt")
    await callback.message.answer_document(file, caption=f"{len(codes)} ta ishlatilmagan kod")
    await callback.answer()
