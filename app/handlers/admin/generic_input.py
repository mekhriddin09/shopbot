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
from aiogram.exceptions import TelegramAPIError
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
    admin_user_profile_kb,
    admin_user_search_results_kb,
)
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.referral_repo import ReferralRepository
from app.repositories.setting_repo import SettingRepository
from app.repositories.user_repo import UserRepository
from app.services.delivery_service import DeliveryService
from app.services.exceptions import DeliveryFailedError, InvalidOrderStateError
from app.services.stock_notify_service import notify_waiters_if_in_stock
from app.states.admin_states import AdminInput
from app.utils.formatting import build_delivered_message, fmt_price
from app.utils.i18n import t

router = Router(name="admin_generic_input")
router.message.filter(IsAdmin())

admin_actions_logger = logging.getLogger("admin_actions")


async def _reflect_delivery_on_admin_card(bot, data: dict, order) -> None:
    """Edit the *original* admin notification (the payment proof photo/
    document/text that started this manual-delivery flow) to show the same
    "delivered at HH:MM, sent: <payload>" confirmation the auto-delivery
    path shows — otherwise that original card is left as a dead end with
    its buttons stripped and no visible outcome at all. Shared by both the
    typed-text and uploaded-file manual-delivery paths below."""
    admin_chat_id = data.get("admin_chat_id")
    admin_message_id = data.get("admin_message_id")
    if not (admin_chat_id and admin_message_id):
        return

    from app.handlers.admin.orders import _delivered_confirmation_block  # local import avoids a cycle

    new_body = (data.get("admin_original_body") or "") + _delivered_confirmation_block(order)
    try:
        if data.get("admin_msg_is_photo"):
            await bot.edit_message_caption(chat_id=admin_chat_id, message_id=admin_message_id, caption=new_body)
        else:
            await bot.edit_message_text(chat_id=admin_chat_id, message_id=admin_message_id, text=new_body)
    except TelegramAPIError:
        pass  # message too old/deleted/caption-too-long — the confirmation below still reaches the admin
    try:
        await bot.edit_message_reply_markup(chat_id=admin_chat_id, message_id=admin_message_id, reply_markup=None)
    except TelegramAPIError:
        pass


async def _product_summary_and_kb(session: AsyncSession, product_id: int):
    """Returns (product, text, keyboard) for the product's root group —
    after editing a field the admin lands back on the grouped screen with
    the new value already visible."""
    from app.handlers.admin.products import render_product_group  # local import avoids cycle

    product = await ProductRepository(session).get_by_id(product_id)
    text, kb = render_product_group(product, "root")
    return product, text, kb


async def _back_to_panel(message: Message, data: dict, text: str, reply_markup=None) -> None:
    """Finish a typed-input step by redrawing the panel screen it started from.

    Typed input unavoidably adds the admin's own message to the chat; what it
    must NOT also add is a bot message that leaves the panel stale. So the
    result goes back onto the original screen, and a fresh message is sent
    only when that screen can no longer be edited.
    """
    from app.utils.screen import edit_panel

    ok = await edit_panel(
        message.bot,
        data.get("panel_chat_id"),
        data.get("panel_message_id"),
        text,
        reply_markup,
    )
    if not ok:
        await message.answer(text, reply_markup=reply_markup)



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
        await _back_to_panel(message, data, f"✅ Mahsulot yaratildi!\n\n{summary}", kb)
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
        await _back_to_panel(message, data, f"✅ Yangilandi!\n\n{summary}", kb)
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

        await _back_to_panel(
            message, data, f"✅ Sovg'a yaratildi!\n\n{_reward_summary(reward)}",
            admin_referral_reward_detail_kb(reward),
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

        await _back_to_panel(
            message, data, f"✅ Yangilandi!\n\n{_reward_summary(reward)}",
            admin_referral_reward_detail_kb(reward),
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
        if product is not None:
            _, summary, kb = await _product_summary_and_kb(session, product.id)
            await _back_to_panel(message, data, f"✅ Kod qo'shildi.{extra}\n\n{summary}", kb)
        else:
            await message.answer(f"✅ Kod qo'shildi.{extra}")
        return

    if action == "settings_edit":
        key = data["key"]
        group = data.get("group", "root")
        if text == "-":
            # Convention for the masked-secret edit flow (API keys/tokens):
            # "-" means "leave it as it is", never a literal value to save.
            await state.clear()
            from app.handlers.admin.settings import render_settings_group  # local import avoids a cycle

            group_text, group_kb = await render_settings_group(session, group)
            await _back_to_panel(
                message, data, "↩️ Bekor qilindi, qiymat o'zgartirilmadi.\n\n" + group_text, group_kb
            )
            return
        await SettingRepository(session).set(key, text)
        admin_actions_logger.info("setting_changed key=%s admin=%s", key, message.from_user.id)
        await state.clear()

        # Re-show the group the setting belongs to, so the admin lands back
        # where they were (with the new value visible) instead of having to
        # navigate in from "⚙️ Sozlamalar" again.
        from app.handlers.admin.settings import render_settings_group  # local import avoids a cycle

        group_text, group_kb = await render_settings_group(session, group)
        await _back_to_panel(message, data, "✅ Sozlama yangilandi.\n\n" + group_text, group_kb)
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
        panel = (data.get("panel_chat_id"), data.get("panel_message_id"))
        src, page = data.get("src"), data.get("page", 0)
        await state.clear()

        from app.handlers.admin.orders import render_order_detail  # local import avoids a cycle
        from app.keyboards.admin_kb import admin_order_detail_kb
        from app.utils.screen import edit_panel

        fresh = await OrderRepository(session).get_by_id(order_id)
        body = "❌ <b>RAD ETILDI</b> — mijozga xabar berildi.\n\n" + (
            await render_order_detail(session, fresh) if fresh else ""
        )
        if not await edit_panel(
            message.bot, *panel, body,
            admin_order_detail_kb(fresh, src=src, page=page) if fresh else None,
        ):
            await message.answer(body)
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
        await _reflect_delivery_on_admin_card(message.bot, data, order)

        panel = (data.get("panel_chat_id"), data.get("panel_message_id"))
        src, page = data.get("src"), data.get("page", 0)
        await state.clear()

        from app.handlers.admin.orders import render_order_detail  # local import avoids a cycle
        from app.keyboards.admin_kb import admin_order_detail_kb
        from app.utils.screen import edit_panel

        fresh = await OrderRepository(session).get_by_id(order_id)
        body = "✅ <b>YETKAZILDI</b> — xabar mijozga yuborildi.\n\n" + (
            await render_order_detail(session, fresh) if fresh else ""
        )
        if not await edit_panel(
            message.bot, *panel, body,
            admin_order_detail_kb(fresh, src=src, page=page) if fresh else None,
        ):
            await message.answer(body)
        return

    if action == "order_search":
        query = text.strip().lstrip("#").upper()
        orders_repo = OrderRepository(session)
        order = await orders_repo.get_by_uuid(query)
        if order is None and query.isdigit():
            # Also accept the internal numeric id — it shows up in logs and
            # in some admin messages, and typing it should just work.
            order = await orders_repo.get_by_id(int(query))
        panel = (data.get("panel_chat_id"), data.get("panel_message_id"))
        await state.clear()

        from app.handlers.admin.orders import render_order_detail  # local import avoids a cycle
        from app.keyboards.admin_kb import admin_order_detail_kb, admin_orders_menu_kb
        from app.utils.screen import edit_panel

        if order is None:
            body = "❌ Bunday buyurtma topilmadi.\n\nID'ni tekshirib, qaytadan urinib ko'ring."
            if not await edit_panel(message.bot, *panel, body, admin_orders_menu_kb()):
                await message.answer(body)
            return

        body = await render_order_detail(session, order)
        if not await edit_panel(message.bot, *panel, body, admin_order_detail_kb(order)):
            await message.answer(body, reply_markup=admin_order_detail_kb(order))
        return

    if action == "user_search":
        query = text.lstrip("@")
        users_repo = UserRepository(session)
        if query.isdigit():
            found = await users_repo.get_by_telegram_id(int(query))
            matches = [found] if found else []
        else:
            matches = await users_repo.search_by_username(query)
        await state.clear()
        if not matches:
            await message.answer("❌ Foydalanuvchi topilmadi.")
            return
        if len(matches) == 1:
            from app.handlers.admin.users import _send_user_profile  # local import avoids cycle

            await _send_user_profile(message, session, matches[0])
            return
        await message.answer(
            f"🔎 {len(matches)} ta mos foydalanuvchi topildi:",
            reply_markup=admin_user_search_results_kb(matches),
        )
        return

    if action == "user_balance_adjust":
        user_id = data["user_id"]
        sign = data["sign"]
        try:
            amount = float(text.replace(" ", "").replace(",", "."))
        except ValueError:
            await message.answer("Noto'g'ri raqam. Faqat son yuboring, masalan: 5000")
            return
        if amount <= 0:
            await message.answer("0 dan katta son yuboring.")
            return

        target = await UserRepository(session).get_by_id(user_id)
        if target is None:
            await message.answer("Foydalanuvchi topilmadi.")
            await state.clear()
            return

        delta = sign * amount
        use_points = bool(data.get("use_points"))
        users_repo = UserRepository(session)
        settings_repo = SettingRepository(session)
        if use_points:
            new_balance = await users_repo.adjust_referral_points(target, delta)
            currency = await settings_repo.get("referral_points_name", "Ball")
        else:
            new_balance = await users_repo.adjust_referral_balance(target, delta)
            currency = await settings_repo.get("referral_currency", "UZS")
        admin_actions_logger.info(
            "user_balance_adjusted user=%s currency=%s delta=%s new_balance=%s admin=%s",
            target.id, "points" if use_points else "balance", delta, new_balance, message.from_user.id,
        )
        await state.clear()
        try:
            await message.bot.send_message(
                target.telegram_id,
                t(
                    target.language,
                    "msg_balance_adjusted_by_admin",
                    sign="+" if delta >= 0 else "-",
                    amount=fmt_price(abs(delta)),
                    balance=fmt_price(new_balance),
                    currency=currency,
                ),
            )
        except TelegramAPIError:
            pass  # user may have blocked the bot — the admin-side confirmation below still shows the new balance

        from app.handlers.admin.users import _build_user_profile_text  # local import avoids cycle

        profile_text = await _build_user_profile_text(session, target)
        await _back_to_panel(
            message, data, f"✅ Balans yangilandi.\n\n{profile_text}",
            admin_user_profile_kb(target.id),
        )
        return

    if action == "add_allowed_phone":
        from app.repositories.allowed_phone_repo import AllowedPhoneRepository
        from app.services.onboarding_service import normalize_phone

        normalized = normalize_phone(text)
        if not normalized:
            await message.answer("Noto'g'ri raqam. Qaytadan yozing (masalan: +7 999 123 45 67).")
            return
        await AllowedPhoneRepository(session).add(normalized)
        admin_actions_logger.info("allowed_phone_added phone=%s admin=%s", normalized, message.from_user.id)
        await state.clear()

        from app.keyboards.admin_kb import admin_phone_whitelist_kb

        entries = await AllowedPhoneRepository(session).list_all()
        await message.answer(f"✅ +{normalized} ro'yxatga qo'shildi.", reply_markup=admin_phone_whitelist_kb(entries))
        return

    if action == "user_send_message":
        user_id = data["user_id"]
        target = await UserRepository(session).get_by_id(user_id)
        if target is None:
            await message.answer("Foydalanuvchi topilmadi.")
            await state.clear()
            return
        await state.clear()
        try:
            await message.bot.send_message(
                target.telegram_id,
                t(target.language, "msg_admin_direct_message_prefix") + "\n\n" + text,
            )
            admin_actions_logger.info("user_direct_message_sent user=%s admin=%s", target.id, message.from_user.id)
            await message.answer("✅ Xabar yuborildi.")
        except TelegramAPIError:
            await message.answer("⚠️ Yuborib bo'lmadi — foydalanuvchi botni bloklagan bo'lishi mumkin.")
        return

    await state.clear()


@router.message(AdminInput.waiting_text, F.document)
async def handle_document_as_text_value(message: Message, session: AsyncSession, state: FSMContext) -> None:
    """Two unrelated file-upload conveniences share this one handler slot
    (both fire while `AdminInput.waiting_text` is active, distinguished by
    `action`):

    - `settings_edit`: upload a `.txt`/`.md` file instead of typing/pasting
      — mainly for a long oferta/terms document that exceeds Telegram's
      ~4096-character single-message limit. The file is *decoded* into text
      and stored as the setting's value.
    - `manual_deliver`: send the customer an actual file (PDF/DOCX/ZIP/
      whatever) as the product itself, instead of typing a text/code
      message — the file is simply *forwarded* (by file_id), never
      downloaded or decoded.

    Every other `waiting_text` action still expects a typed message, so
    this silently no-ops for those (state stays open, admin can still type)."""
    data = await state.get_data()
    action = data.get("action")
    document = message.document

    if action == "manual_deliver":
        order_id = data["order_id"]
        file_name = document.file_name or "fayl"
        descriptive = f"[Fayl] {file_name}"
        delivery = DeliveryService(session)
        try:
            order = await delivery.deliver_manual_message(order_id, message.from_user.id, descriptive)
        except InvalidOrderStateError as exc:
            await message.answer(str(exc))
            await state.clear()
            return

        lang = order.user.language
        caption = build_delivered_message(lang, order, descriptive)
        try:
            if len(caption) <= 1024:
                await message.bot.send_document(order.user.telegram_id, document.file_id, caption=caption)
            else:
                # Telegram caption cap (1024 chars) — send the file plain,
                # then the (longer) confirmation/instructions as a follow-up.
                await message.bot.send_document(order.user.telegram_id, document.file_id)
                await message.bot.send_message(order.user.telegram_id, caption)
        except TelegramAPIError:
            await message.answer("⚠️ Fayl mijozga yuborib bo'lmadi — foydalanuvchi botni bloklagan bo'lishi mumkin.")
            await state.clear()
            return

        admin_actions_logger.info(
            "order_manual_delivered_file order=%s file=%s admin=%s", order_id, file_name, message.from_user.id
        )
        from app.services.referral_service import ReferralService  # local import avoids a cycle

        await ReferralService(session).credit_for_delivered_order(order, message.bot)
        await _reflect_delivery_on_admin_card(message.bot, data, order)

        await state.clear()
        await message.answer("✅ Fayl mijozga yuborildi va buyurtma yakunlandi.")
        return

    if action != "settings_edit":
        return

    filename = (document.file_name or "").lower()
    if not (filename.endswith(".txt") or filename.endswith(".md")):
        await message.answer("Iltimos, .txt (yoki .md) formatidagi fayl yuboring, yoki matnni to'g'ridan-to'g'ri yozing.")
        return
    if document.file_size and document.file_size > 2_000_000:
        await message.answer("Fayl juda katta (2MB dan oshmasligi kerak).")
        return

    file = await message.bot.get_file(document.file_id)
    buffer = await message.bot.download_file(file.file_path)
    text = buffer.read().decode("utf-8", errors="ignore").strip()
    if not text:
        await message.answer("Fayl bo'sh ko'rinadi. Boshqa fayl yuboring.")
        return

    key = data["key"]
    group = data.get("group", "root")
    await SettingRepository(session).set(key, text)
    admin_actions_logger.info("setting_changed_via_file key=%s chars=%s admin=%s", key, len(text), message.from_user.id)
    await state.clear()
    await message.answer(f"✅ Sozlama fayldan yangilandi ({len(text)} belgi).")

    from app.handlers.admin.settings import render_settings_group  # local import avoids a cycle

    group_text, group_kb = await render_settings_group(session, group)
    await message.answer(group_text, reply_markup=group_kb)


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
