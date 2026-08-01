from __future__ import annotations

import io

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

router = Router(name="admin_inventory")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(AdminInventoryCB.filter(F.action == "menu"))
async def inventory_menu(callback: CallbackQuery, callback_data: AdminInventoryCB, session: AsyncSession) -> None:
    unused = await InventoryRepository(session).count_unused(callback_data.product_id)
    await callback.message.edit_text(
        f"\U0001F4E6 Inventar\nMavjud (ishlatilmagan) kodlar: {unused}",
        reply_markup=admin_inventory_menu_kb(callback_data.product_id),
    )
    await callback.answer()


@router.callback_query(AdminInventoryCB.filter(F.action == "add_one"))
async def inventory_add_one(callback: CallbackQuery, callback_data: AdminInventoryCB, state: FSMContext) -> None:
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(action="inventory_add_one", product_id=callback_data.product_id)
    await callback.message.answer("Yangi kodni yozing (bitta):")
    await callback.answer()


@router.callback_query(AdminInventoryCB.filter(F.action == "bulk"))
async def inventory_bulk_start(callback: CallbackQuery, callback_data: AdminInventoryCB, state: FSMContext) -> None:
    await state.set_state(AdminInput.waiting_codes_file_or_text)
    await state.update_data(action="inventory_bulk", product_id=callback_data.product_id)
    await callback.message.answer(
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
    preview = "\n".join(c.code for c in codes[:30])
    more = f"\n... va yana {len(codes) - 30} ta" if len(codes) > 30 else ""
    await callback.message.answer(f"\U0001F4CB Ishlatilmagan kodlar ({len(codes)}):\n\n<code>{preview}</code>{more}")
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
    unused = await InventoryRepository(session).count_unused(callback_data.product_id)
    await callback.message.edit_text(
        f"\U0001F4E6 Inventar\nMavjud (ishlatilmagan) kodlar: {unused}",
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
        f"\U0001F4E6 Inventar\nMavjud (ishlatilmagan) kodlar: 0",
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
