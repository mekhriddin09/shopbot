from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.enums import DeliveryMode
from app.filters.is_admin import IsAdmin
from app.keyboards.admin_kb import (
    admin_product_detail_kb,
    admin_products_list_kb,
    confirm_delete_product_kb,
    delivery_mode_kb,
    product_lang_pick_kb,
)
from app.keyboards.callback_data import AdminProductCB
from app.repositories.product_repo import ProductRepository
from app.states.admin_states import AdminInput
from app.utils.formatting import fmt_price

router = Router(name="admin_products")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

admin_actions_logger = logging.getLogger("admin_actions")

_LANG_LABELS = {"uz": "o'zbekcha", "ru": "ruscha", "en": "inglizcha"}

FIELD_PROMPTS = {
    "name": "Yangi nomni yozing (bu — hech qaysi tilga moslanmagan hollarda ko'rsatiladigan standart nom):",
    "description": "Yangi tavsifni yozing (bu — hech qaysi tilga moslanmagan hollarda ko'rsatiladigan standart tavsif):",
    "price": "Yangi narxni raqamda yozing (masalan: 25000):",
    "price_usd": "Kripto (USD) narxini yozing (masalan: 4.00). Kripto to'lovni o'chirish uchun '-' yuboring:",
    "emoji": "Yangi emoji yuboring:",
    "sort_order": "Tartib raqamini yozing (butun son, kichigi tepada turadi):",
    "payment_instructions": "Ushbu mahsulot uchun maxsus to'lov ma'lumotini yozing (bo'sh qoldirish uchun '-' yuboring):",
    "provider_key": "Provider kalitini kiriting (masalan: reseller_api yoki mock_provider):",
    "external_product_id": (
        "Tashqi provayderdagi ushbu mahsulotning ID'sini yozing "
        "(masalan: gemini). Kerak bo'lmasa '-' yuboring:"
    ),
    **{
        f"name_{code}": f"Mahsulot nomini {label} tilida yozing. O'chirish uchun '-' yuboring:"
        for code, label in _LANG_LABELS.items()
    },
    **{
        f"description_{code}": f"Mahsulot tavsifini {label} tilida yozing. O'chirish uchun '-' yuboring:"
        for code, label in _LANG_LABELS.items()
    },
    **{
        f"delivery_instructions_{code}": (
            f"Mijozga mahsulot yuborilgandan keyin qo'shimcha ko'rsatiladigan matnni "
            f"{label} tilida yozing (masalan: qanday login qilish/ishlatish kerakligi). "
            f"O'chirish uchun '-' yuboring:"
        )
        for code, label in _LANG_LABELS.items()
    },
}


def _product_summary(product) -> str:
    mode_label = {
        DeliveryMode.INVENTORY: "Ichki inventar",
        DeliveryMode.MANUAL: "Qo'lda yetkazish",
        DeliveryMode.API: (
            f"Tashqi API ({product.provider_key or '—'}"
            + (f", ID: {product.external_product_id}" if product.external_product_id else "")
            + ")"
        ),
    }[product.delivery_mode]
    visibility = "\U0001F7E2 Ko'rinadi" if product.is_visible else "⚪ Yashirilgan"
    price_usd_line = (
        f"\U0001FA99 Kripto narx: ${float(product.price_usd):.2f}\n"
        if product.price_usd is not None
        else "\U0001FA99 Kripto narx: o'rnatilmagan\n"
    )
    def _lang_coverage(field_base: str) -> str:
        set_langs = [code for code in _LANG_LABELS if getattr(product, f"{field_base}_{code}", None)]
        return ", ".join(set_langs) if set_langs else "faqat standart"

    delivery_instructions_line = (
        f"\U0001F4DD Yetkazishdan keyingi xabar (tillar: {_lang_coverage('delivery_instructions')})\n"
        if getattr(product, "delivery_instructions", None) or _lang_coverage("delivery_instructions") != "faqat standart"
        else "\U0001F4DD Yetkazishdan keyingi xabar: o'rnatilmagan\n"
    )
    return (
        f"{product.emoji} <b>{product.name}</b>\n\n"
        f"{product.description or '-'}\n\n"
        f"\U0001F310 Nomi tarjimalari: {_lang_coverage('name')}\n"
        f"\U0001F310 Tavsif tarjimalari: {_lang_coverage('description')}\n"
        f"\U0001F4B0 Narx: {fmt_price(float(product.price))} {product.currency}\n"
        f"{price_usd_line}"
        f"\U0001F4E6 Yetkazish rejimi: {mode_label}\n"
        f"\U0001F522 Tartib: {product.sort_order}\n"
        f"{delivery_instructions_line}"
        f"{visibility}"
    )


@router.message(F.text == "\U0001F6CD️ Mahsulotlar")
async def products_menu(message: Message, session: AsyncSession) -> None:
    products = await ProductRepository(session).list_all()
    await message.answer("\U0001F6CD️ Mahsulotlar ro'yxati:", reply_markup=admin_products_list_kb(products))


@router.callback_query(AdminProductCB.filter(F.action == "list"))
async def products_list_cb(callback: CallbackQuery, session: AsyncSession) -> None:
    products = await ProductRepository(session).list_all()
    await callback.message.edit_text(
        "\U0001F6CD️ Mahsulotlar ro'yxati:", reply_markup=admin_products_list_kb(products)
    )
    await callback.answer()


@router.callback_query(AdminProductCB.filter(F.action == "open"))
async def product_open(callback: CallbackQuery, callback_data: AdminProductCB, session: AsyncSession) -> None:
    product = await ProductRepository(session).get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    await callback.message.edit_text(_product_summary(product), reply_markup=admin_product_detail_kb(product))
    await callback.answer()


@router.callback_query(AdminProductCB.filter(F.action == "add"))
async def product_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(action="new_product_name")
    await callback.message.answer("Yangi mahsulot nomini yozing:")
    await callback.answer()


@router.callback_query(AdminProductCB.filter(F.action == "edit_field"))
async def product_edit_field(callback: CallbackQuery, callback_data: AdminProductCB, state: FSMContext) -> None:
    field = callback_data.field
    if field == "image":
        await state.set_state(AdminInput.waiting_image)
        await state.update_data(action="edit_product_field", product_id=callback_data.product_id, field=field)
        await callback.message.answer("Yangi rasmni yuboring:")
        await callback.answer()
        return

    prompt = FIELD_PROMPTS.get(field, "Yangi qiymatni yozing:")
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(action="edit_product_field", product_id=callback_data.product_id, field=field)
    await callback.message.answer(prompt)
    await callback.answer()


@router.callback_query(AdminProductCB.filter(F.action == "pick_lang_field"))
async def product_pick_lang_field(callback: CallbackQuery, callback_data: AdminProductCB) -> None:
    await callback.message.edit_reply_markup(
        reply_markup=product_lang_pick_kb(callback_data.product_id, callback_data.field)
    )
    await callback.answer()


@router.callback_query(AdminProductCB.filter(F.action == "set_mode"))
async def product_set_mode(callback: CallbackQuery, callback_data: AdminProductCB) -> None:
    await callback.message.edit_reply_markup(reply_markup=delivery_mode_kb(callback_data.product_id))
    await callback.answer()


@router.callback_query(AdminProductCB.filter(F.action == "apply_mode"))
async def product_apply_mode(
    callback: CallbackQuery, callback_data: AdminProductCB, session: AsyncSession, state: FSMContext
) -> None:
    products = ProductRepository(session)
    product = await products.get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    new_mode = DeliveryMode(callback_data.field)
    await products.update(product, delivery_mode=new_mode)

    if new_mode == DeliveryMode.API:
        await state.set_state(AdminInput.waiting_text)
        await state.update_data(action="edit_product_field", product_id=product.id, field="provider_key")
        await callback.message.answer(FIELD_PROMPTS["provider_key"])
    await callback.message.edit_text(_product_summary(product), reply_markup=admin_product_detail_kb(product))
    await callback.answer("Yetkazish rejimi yangilandi ✅")


@router.callback_query(AdminProductCB.filter(F.action == "toggle_visibility"))
async def product_toggle_visibility(callback: CallbackQuery, callback_data: AdminProductCB, session: AsyncSession) -> None:
    products = ProductRepository(session)
    product = await products.get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    await products.set_visibility(product, not product.is_visible)
    await callback.message.edit_text(_product_summary(product), reply_markup=admin_product_detail_kb(product))
    await callback.answer()


@router.callback_query(AdminProductCB.filter(F.action == "delete"))
async def product_delete_confirm(callback: CallbackQuery, callback_data: AdminProductCB) -> None:
    await callback.message.edit_reply_markup(reply_markup=confirm_delete_product_kb(callback_data.product_id))
    await callback.answer()


@router.callback_query(AdminProductCB.filter(F.action == "confirm_delete"))
async def product_delete(callback: CallbackQuery, callback_data: AdminProductCB, session: AsyncSession) -> None:
    products = ProductRepository(session)
    product = await products.get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    admin_actions_logger.info(
        "product_deleted id=%s name=%s admin=%s", product.id, product.name, callback.from_user.id
    )
    await products.delete(product)
    all_products = await products.list_all()
    await callback.message.edit_text("✅ Mahsulot o'chirildi.", reply_markup=admin_products_list_kb(all_products))
    await callback.answer()
