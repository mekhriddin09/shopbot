from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters.is_admin import IsAdmin
from app.keyboards.admin_kb import (
    ADMIN_BTN_BROADCAST,
    ADMIN_BTN_EXIT,
    ADMIN_BTN_ORDERS,
    ADMIN_BTN_SETTINGS,
    admin_broadcast_menu_kb,
    admin_main_menu_kb,
    admin_orders_menu_kb,
)
from app.keyboards.user_kb import ADMIN_PANEL_BTN, main_menu_kb
from app.states.admin_states import AdminInput

router = Router(name="admin_menu")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

_INPUT_STATES = {
    AdminInput.waiting_text.state,
    AdminInput.waiting_image.state,
    AdminInput.waiting_codes_file_or_text.state,
}


async def _cancel_pending_input(state: FSMContext) -> str:
    """These bottom-keyboard buttons (Orders/Settings/Broadcast/Admin
    panel/Exit) have no state filter — they fire from anywhere, including
    while the admin is mid-way through a "type the new value" flow
    dispatched in generic_input.py. Before this, tapping one of them while
    typing a price/setting/reason silently abandoned that flow: FSM data
    (product_id, field, panel coordinates, ...) was gone with nothing said
    about it — exactly the "o'zgartirsam bosh menyuga otib qoladi" (it
    jumps back to the main menu) complaint. Now that abandonment is
    explicit: it's still cancelled (a half-typed edit can't be resumed
    later anyway), but the admin is told so, instead of just landing
    somewhere else and wondering what happened."""
    current = await state.get_state()
    if current in _INPUT_STATES:
        await state.clear()
        return "⚠️ Oldingi amal (matn/fayl kiritish) bekor qilindi.\n\n"
    return ""


@router.message(Command("admin"))
@router.message(F.text == ADMIN_PANEL_BTN)
async def open_admin_panel(message: Message, state: FSMContext) -> None:
    note = await _cancel_pending_input(state)
    await state.clear()
    await message.answer(note + "\U0001F6E0️ Admin panel", reply_markup=admin_main_menu_kb())


@router.message(F.text == ADMIN_BTN_ORDERS)
async def goto_orders(message: Message, state: FSMContext) -> None:
    # One screen per section: everything inside Orders now edits this very
    # message, so the section never grows past a single card in the chat.
    note = await _cancel_pending_input(state)
    await message.answer(note + "\U0001F4E5 Buyurtmalar bo'limi:", reply_markup=admin_orders_menu_kb())


@router.message(F.text == ADMIN_BTN_SETTINGS)
async def goto_settings(message: Message, session: AsyncSession, state: FSMContext) -> None:
    from app.handlers.admin.settings import render_settings_group  # local import avoids a cycle

    note = await _cancel_pending_input(state)
    text, kb = await render_settings_group(session, "root")
    await message.answer(note + text, reply_markup=kb)


@router.message(F.text == ADMIN_BTN_BROADCAST)
async def goto_broadcast(message: Message, state: FSMContext) -> None:
    note = await _cancel_pending_input(state)
    await state.clear()
    await message.answer(note + "\U0001F4E2 Kimga xabar yubormoqchisiz?", reply_markup=admin_broadcast_menu_kb())


@router.message(F.text == ADMIN_BTN_EXIT)
async def exit_admin_panel(message: Message, lang: str, state: FSMContext) -> None:
    note = await _cancel_pending_input(state)
    await state.clear()
    # This handler is itself gated by the router-level IsAdmin filter, so if
    # it fired at all, the sender is definitely an admin.
    await message.answer(note + "Admin paneldan chiqdingiz.", reply_markup=main_menu_kb(lang, is_admin=True))
