"""Single dispatch point for every generic AdminInput FSM state.

The admin panel has dozens of "type something to change it" flows (edit
product name, edit price, edit a setting, write a rejection reason, write
the manual-delivery message, ...). Instead of one StatesGroup + one handler
per flow, every such flow sets the same `AdminInput.waiting_text` (or
`waiting_image` / `waiting_codes_file_or_text`) state plus an `action` key
in the FSM data, and the handlers below dispatch on that key. See
`app/states/admin_states.py` for the rationale.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.filters.is_admin import IsAdmin
from app.keyboards.admin_kb import (
    admin_broadcast_confirm_kb,
    admin_product_detail_kb,
    admin_products_list_kb,
    admin_referral_reward_detail_kb,
)
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.referral_repo import ReferralRepository
from app.repositories.setting_repo import SettingRepository
from app.services.delivery_service import DeliveryService
from app.services.exceptions import DeliveryFailedError, InvalidOrderStateError
from app.services.stock_notify_service import notify_waiters_if_in_stock
from app.states.admin_states import AdminInput
from app.utils.formatting import build_delivered_message
from app.utils.i18n import t

router = Router(name="admin_generic_input")
router.message.filter(IsAdmin())

admin_actions_logger = logging.getLogger("admin_actions")


async def _product_summary_and_kb(session: AsyncSession, product_id: int):
    from app.handlers.admin.products import _product_summary  # local import avoids cycle

    product = await ProductRepository(session).get_by_id(product_id)
    return product, _product_summary(product), admin_product_detail_kb(product)


@router.message(AdminInput.waiting_text, F.text)
async def handle_text_input(message: Message, session: AsyncSession, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    action = data.get("action")
    text = message.text.strip()

    if action == "new_product_name":
        await state.update_data(action="new_product_price", name=text)
        await message.answer("Narxni raqamda yozing (masalan: 25000):")
        return

    if action == "new_product_price":
        try:
            price = float(text.replace(" ", "").replace(",", "."))
        except ValueError:
            await message.answer("Narx noto'g'ri. Faqat raqam yuboring, masalan: 25000")
            return
        name = data.get("name", "Yangi mahsulot")
        product = await ProductRepository(session).create(name=name, price=price)
        admin_actions_logger.info("product_created id=%s name=%s admin=%s", product.id, name, message.from_user.id)
        await state.clear()
        _, summary, kb = await _product_summary_and_kb(session, product.id)
        await message.answer(f"✅ Mahsulot yaratildi!\n\n{summary}", reply_markup=kb)
        return

    if action == "edit_product_field":
        product_id = data["product_id"]
        field = data["field"]
        products = ProductRepository(session)
        product = await products.get_by_id(product_id)
        if product is None:
            await message.answer("Mahsulot topilmadi.")
            await state.clear()
            return

        if field == "price":
            try:
                value: object = float(text.replace(" ", "").replace(",", "."))
            except ValueError:
                await message.answer("Narx noto'g'ri. Faqat raqam yuboring.")
                return
        elif field == "price_usd":
            if text == "-":
                value = None
            else:
                try:
                    value = float(text.replace(" ", "").replace(",", "."))
                except ValueError:
                    await message.answer("Narx noto'g'ri. Faqat raqam yuboring (masalan 4.00) yoki '-' yuboring.")
                    return
        elif field == "price_stars":
            if text == "-":
                value = None
            else:
                try:
                    value = int(text)
                except ValueError:
                    await message.answer("Narx noto'g'ri. Faqat butun son yuboring (masalan 100) yoki '-' yuboring.")
                    return
                if value < 1:
                    await message.answer("1 dan kichik bo'lmasligi kerak.")
                    return
        elif field in ("sort_order", "min_order_qty", "max_order_qty"):
            try:
                value = int(text)
            except ValueError:
                await message.answer("Butun son yuboring.")
                return
            if field in ("min_order_qty", "max_order_qty") and value < 1:
                await message.answer("1 dan kichik bo'lmasligi kerak.")
                return
        elif field in (
            "payment_instructions",
            "external_product_id",
            "delivery_instructions",
            "name_uz", "name_ru", "name_en",
            "description_uz", "description_ru", "description_en",
            "delivery_instructions_uz", "delivery_instructions_ru", "delivery_instructions_en",
        ):
            value = None if text == "-" else text
        else:
            value = text

        await products.update(product, **{field: value})
        admin_actions_logger.info(
            "product_field_edited id=%s field=%s admin=%s", product.id, field, message.from_user.id
        )

        if field == "provider_key":
            # Chain straight into asking for the external product ID too —
            # most external-API providers (e.g. a reseller with many
            # products behind one API key) need it to know *which* product
            # to fetch, so ask right away instead of making the admin hunt
            # for a separate button.
            from app.handlers.admin.products import FIELD_PROMPTS  # local import avoids cycle

            await state.set_state(AdminInput.waiting_text)
            await state.update_data(action="edit_product_field", product_id=product.id, field="external_product_id")
            await message.answer(f"✅ Provider saqlandi.\n\n{FIELD_PROMPTS['external_product_id']}")
            return

        await state.clear()
        _, summary, kb = await _product_summary_and_kb(session, product.id)
        await message.answer(f"✅ Yangilandi!\n\n{summary}", reply_markup=kb)
        return

    if action == "new_reward_name":
        await state.update_data(action="new_reward_cost", name=text)
        await message.answer("Narxini (referral balansidan yechiladigan ball/summa) raqamda yozing (masalan: 20000):")
        return

    if action == "new_reward_cost":
        try:
            cost = float(text.replace(" ", "").replace(",", "."))
        except ValueError:
            await message.answer("Narx noto'g'ri. Faqat raqam yuboring, masalan: 20000")
            return
        name = data.get("name", "Yangi sovg'a")
        reward = await ReferralRepository(session).create_reward(name=name, cost=cost)
        admin_actions_logger.info("referral_reward_created id=%s name=%s admin=%s", reward.id, name, message.from_user.id)
        await state.clear()
        from app.handlers.admin.referral_rewards import _reward_summary  # local import avoids cycle

        await message.answer(
            f"✅ Sovg'a yaratildi!\n\n{_reward_summary(reward)}",
            reply_markup=admin_referral_reward_detail_kb(reward),
        )
        return

    if action == "edit_reward_field":
        reward_id = data["reward_id"]
        field = data["field"]
        referrals = ReferralRepository(session)
        reward = await referrals.get_reward(reward_id)
        if reward is None:
            await message.answer("Sovg'a topilmadi.")
            await state.clear()
            return

        if field == "cost":
            try:
                value: object = float(text.replace(" ", "").replace(",", "."))
            except ValueError:
                await message.answer("Narx noto'g'ri. Faqat raqam yuboring.")
                return
        elif field == "description":
            value = None if text == "-" else text
        else:
            value = text

        await referrals.update_reward(reward, **{field: value})
        admin_actions_logger.info(
            "referral_reward_field_edited id=%s field=%s admin=%s", reward.id, field, message.from_user.id
        )
        await state.clear()
        from app.handlers.admin.referral_rewards import _reward_summary  # local import avoids cycle

        await message.answer(
            f"✅ Yangilandi!\n\n{_reward_summary(reward)}",
            reply_markup=admin_referral_reward_detail_kb(reward),
        )
        return

    if action == "inventory_add_one":
        product_id = data["product_id"]
        await InventoryRepository(session).add_code(product_id, text)
        admin_actions_logger.info("inventory_code_added product=%s admin=%s", product_id, message.from_user.id)
        product = await ProductRepository(session).get_by_id(product_id)
        notified = await notify_waiters_if_in_stock(session, message.bot, product) if product else 0
        await state.clear()
        extra = f"\n🔔 {notified} ta kutayotgan foydalanuvchiga xabar berildi." if notified else ""
        await message.answer(f"✅ Kod qo'shildi.{extra}")
        return

    if action == "settings_edit":
        key = data["key"]
        if text == "-":
            # Convention for the masked-secret edit flow (API keys/tokens):
            # "-" means "leave it as it is", never a literal value to save.
            await state.clear()
            await message.answer("↩️ Bekor qilindi, qiymat o'zgartirilmadi.")
            return
        await SettingRepository(session).set(key, text)
        admin_actions_logger.info("setting_changed key=%s admin=%s", key, message.from_user.id)
        await state.clear()
        await message.answer("✅ Sozlama yangilandi.")
        return

    if action == "reject_reason":
        order_id = data["order_id"]
        reason = None if text == "-" else text
        delivery = DeliveryService(session)
        try:
            order = await delivery.reject_order(order_id, message.from_user.id, reason)
        except InvalidOrderStateError as exc:
            await message.answer(str(exc))
            await state.clear()
            return
        admin_actions_logger.info("order_rejected order=%s admin=%s", order_id, message.from_user.id)
        lang = order.user.language
        await message.bot.send_message(
            order.user.telegram_id,
            t(lang, "msg_order_rejected_notify", order_uuid=order.order_uuid, reason=reason or "-"),
        )
        await state.clear()
        await message.answer("❌ Buyurtma rad etildi va foydalanuvchiga xabar berildi.")
        return

    if action == "broadcast_send":
        from app.handlers.admin.broadcast import _resolve_recipients  # local import avoids a cycle

        audience = data.get("audience")
        product_id = data.get("product_id", 0)
        recipients = await _resolve_recipients(session, audience, product_id)
        await state.update_data(action="broadcast_awaiting_confirm", message_text=text)
        preview = text if len(text) <= 500 else text[:500] + "…"
        await message.answer(
            f"\U0001F4E2 Ushbu xabar <b>{len(recipients)}</b> ta foydalanuvchiga yuboriladi:\n\n"
            f"{preview}\n\nTasdiqlaysizmi?",
            reply_markup=admin_broadcast_confirm_kb(),
        )
        return

    if action == "broadcast_awaiting_confirm":
        await message.answer("Iltimos, yuqoridagi tugmalardan birini tanlang (✅ Ha, yuborish / ❌ Bekor qilish).")
        return

    if action == "manual_deliver":
        order_id = data["order_id"]
        delivery = DeliveryService(session)
        try:
            order = await delivery.deliver_manual_message(order_id, message.from_user.id, text)
        except InvalidOrderStateError as exc:
            await message.answer(str(exc))
            await state.clear()
            return
        admin_actions_logger.info("order_manual_delivered order=%s admin=%s", order_id, message.from_user.id)
        lang = order.user.language
        await message.bot.send_message(
            order.user.telegram_id,
            build_delivered_message(lang, order, text),
        )
        from app.services.referral_service import ReferralService  # local import avoids a cycle

        await ReferralService(session).credit_for_delivered_order(order, message.bot)
        await state.clear()
        await message.answer("✅ Xabar mijozga yuborildi va buyurtma yakunlandi.")
        return

    await state.clear()


@router.message(AdminInput.waiting_image, F.photo)
async def handle_image_input(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    action = data.get("action")
    file_id = message.photo[-1].file_id

    if action == "edit_product_field" and data.get("field") == "image":
        product_id = data["product_id"]
        products = ProductRepository(session)
        product = await products.get_by_id(product_id)
        if product is None:
            await message.answer("Mahsulot topilmadi.")
            await state.clear()
            return
        await products.update(product, image_file_id=file_id)
        admin_actions_logger.info("product_image_updated id=%s admin=%s", product.id, message.from_user.id)
        await state.clear()
        _, summary, kb = await _product_summary_and_kb(session, product.id)
        await message.answer_photo(file_id, caption=f"✅ Rasm yangilandi!\n\n{summary}", reply_markup=kb)
        return

    await state.clear()


@router.message(AdminInput.waiting_image)
async def handle_image_input_invalid(message: Message) -> None:
    await message.answer("Iltimos, rasm yuboring.")


@router.message(AdminInput.waiting_codes_file_or_text, F.document)
async def handle_bulk_document(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("action") != "inventory_bulk":
        await state.clear()
        return
    product_id = data["product_id"]
    file = await message.bot.get_file(message.document.file_id)
    buffer = await message.bot.download_file(file.file_path)
    text = buffer.read().decode("utf-8", errors="ignore")
    codes = [line for line in text.splitlines() if line.strip()]
    count = await InventoryRepository(session).bulk_import(product_id, codes)
    admin_actions_logger.info("inventory_bulk_imported product=%s count=%s admin=%s", product_id, count, message.from_user.id)
    product = await ProductRepository(session).get_by_id(product_id)
    notified = await notify_waiters_if_in_stock(session, message.bot, product) if product else 0
    await state.clear()
    extra = f"\n🔔 {notified} ta kutayotgan foydalanuvchiga xabar berildi." if notified else ""
    await message.answer(f"✅ {count} ta kod import qilindi.{extra}")


@router.message(AdminInput.waiting_codes_file_or_text, F.text)
async def handle_bulk_text(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("action") != "inventory_bulk":
        await state.clear()
        return
    product_id = data["product_id"]
    codes = [line for line in message.text.splitlines() if line.strip()]
    count = await InventoryRepository(session).bulk_import(product_id, codes)
    admin_actions_logger.info("inventory_bulk_imported product=%s count=%s admin=%s", product_id, count, message.from_user.id)
    product = await ProductRepository(session).get_by_id(product_id)
    notified = await notify_waiters_if_in_stock(session, message.bot, product) if product else 0
    await state.clear()
    extra = f"\n🔔 {notified} ta kutayotgan foydalanuvchiga xabar berildi." if notified else ""
    await message.answer(f"✅ {count} ta kod import qilindi.{extra}")
