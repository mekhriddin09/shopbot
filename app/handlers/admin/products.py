from __future__ import annotations

import logging
from html import escape as html_escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.enums import DeliveryMode
from app.filters.is_admin import IsAdmin
from app.keyboards.base_buttons import InlineKeyboardButton
from app.keyboards.admin_kb import (
    PRODUCT_GROUPS,
    TOGGLEABLE_FIELDS,
    admin_product_detail_kb,
    admin_products_archive_kb,
    admin_products_list_kb,
    confirm_delete_product_kb,
    delivery_mode_kb,
    product_lang_pick_kb,
)
from app.keyboards.callback_data import AdminProductCB
from app.repositories.product_repo import ProductRepository
from app.states.admin_states import AdminInput
from app.utils.formatting import fmt_price, product_emoji_html
from app.utils.screen import show

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
    "price_stars": "Telegram Stars narxini butun sonda yozing (masalan: 100). Stars to'lovni o'chirish uchun '-' yuboring:",
    "emoji": "Yangi emoji yuboring (oddiy yoki animatsiyali/Premium emoji ham bo'lishi mumkin):",
    "sort_order": "Tartib raqamini yozing (butun son, kichigi tepada turadi):",
    "payment_instructions": "Ushbu mahsulot uchun maxsus to'lov ma'lumotini yozing (bo'sh qoldirish uchun '-' yuboring):",
    "external_product_id": (
        "Tashqi provayderdagi ushbu mahsulotning ID'sini yozing "
        "(masalan: gemini). Kerak bo'lmasa '-' yuboring:"
    ),
    "min_order_qty": "Bitta buyurtmada kamida nechta dona sotib olish kerakligini yozing (butun son, masalan: 1):",
    "max_order_qty": "Bitta buyurtmada ko'pi bilan nechta dona sotib olish mumkinligini yozing (butun son, masalan: 10):",
    "referral_reward_value": (
        "Ushbu mahsulot uchun referral bonusini yozing:\n"
        "• Qat'iy summa — masalan: 5000\n"
        "• Foiz — masalan: 2%\n\n"
        "Bo'sh qoldirish (umumiy sozlamadagi birinchi/keyingi buyurtma qiymatiga qaytarish) uchun "
        "'-' yuboring:"
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


_MODE_LABELS = {
    DeliveryMode.INVENTORY: "\U0001F4E6 Ichki inventar",
    DeliveryMode.MANUAL: "✍️ Qo'lda yetkazish",
    DeliveryMode.API: "\U0001F310 Tashqi API",
}


def _lang_coverage(product, field_base: str) -> str:
    """Which languages this per-language field is filled in for — the one
    thing an admin actually needs to know at a glance about it."""
    langs = [code.upper() for code in _LANG_LABELS if getattr(product, f"{field_base}_{code}", None)]
    return ", ".join(langs) if langs else "—"


def _short(value, limit: int = 40) -> str:
    """One-line preview of a field's raw stored value, always wrapped in
    `<code>...</code>` by callers below. Escaped for HTML: a description
    edited with rich formatting can legitimately contain real `<b>`/
    `<tg-emoji>`/etc. tags (see generic_input.py's rich-text conversion),
    and a plain field like a name can contain an accidental stray "<" or
    "&" — either way, dropping raw HTML/text straight into `<code>` breaks
    Telegram's message parsing outright (this was crashing the "Asosiy
    ma'lumot" screen for any product whose description had been formatted
    with bold/italic/etc). Escaping shows the true stored text as visible
    text, which is exactly right for a technical preview like this one."""
    text = " ".join(str(value).split()) if value not in (None, "") else ""
    if not text:
        return "—"
    text = text if len(text) <= limit else text[: limit - 1] + "…"
    return html_escape(text)


def _product_summary(product) -> str:
    """Short header shown above every product screen: what this product is
    and whether it's live."""
    visibility = "\U0001F7E2 Faol" if product.is_visible else "\U0001F5C4️ Arxivda (mijozlar ko'rmaydi)"
    return (
        f"{product_emoji_html(product)} <b>{html_escape(product.name)}</b>\n"
        f"\U0001F4B5 {fmt_price(float(product.price))} {product.currency} · {_MODE_LABELS[product.delivery_mode]}\n"
        f"{visibility}"
    )


def render_product_group(product, group: str = "root") -> tuple[str, object]:
    """Text + keyboard for one product group, listing current values
    inline. Driven by PRODUCT_GROUPS so buttons and values can't drift."""
    spec = PRODUCT_GROUPS.get(group) or PRODUCT_GROUPS["root"]
    lines = [_product_summary(product), "", spec["title"]]
    if spec.get("intro"):
        lines.append("")
        lines.append(spec["intro"])

    values: list[str] = []
    for kind, key, label in spec["items"]:
        if kind == "field":
            values.append(f"• {label}: <code>{_short(getattr(product, key, None))}</code>")
        elif kind == "api_only_field":
            if product.delivery_mode == DeliveryMode.API:
                values.append(f"• {label}: <code>{_short(getattr(product, key, None))}</code>")
        elif kind == "provider_picker":
            if product.delivery_mode == DeliveryMode.API:
                from app.keyboards.admin_kb import _PROVIDER_LABELS  # local import avoids a cycle

                shown = _PROVIDER_LABELS.get(product.provider_key, product.provider_key) if product.provider_key else "—"
                values.append(f"• {label}: <code>{shown}</code>")
        elif kind == "lang":
            values.append(f"• {label}: {_lang_coverage(product, key)}")
        elif kind == "image":
            values.append(f"• {label}: {'✅ bor' if product.image_file_id else '—'}")
        elif kind == "mode":
            values.append(f"• {label}: <b>{_MODE_LABELS[product.delivery_mode]}</b>")
        elif kind == "toggle":
            values.append(f"• {label}: <b>{'✅ yoqilgan' if getattr(product, key, False) else '❌ o‘chirilgan'}</b>")

    if values:
        lines.append("")
        lines.extend(values)

    return "\n".join(lines), admin_product_detail_kb(product, group)


def _group_of_lang_field(field_base: str) -> str:
    """Which product group a per-language field belongs to, so the language
    picker's Back button returns where the admin came from."""
    for name, spec in PRODUCT_GROUPS.items():
        if any(kind == "lang" and key == field_base for kind, key, _ in spec["items"]):
            return name
    return "root"


async def _show_products_list(message, session: AsyncSession) -> None:
    products = ProductRepository(session)
    visible = [p for p in await products.list_all() if p.is_visible]
    archived = [p for p in await products.list_all() if not p.is_visible]
    text = (
        f"\U0001F6CD️ <b>Mahsulotlar</b> — {len(visible)} ta faol"
        + (f", {len(archived)} ta arxivda" if archived else "")
    )
    await message.answer(text, reply_markup=admin_products_list_kb(visible, len(archived)))


@router.message(F.text == "\U0001F6CD️ Mahsulotlar")
async def products_menu(message: Message, session: AsyncSession) -> None:
    await _show_products_list(message, session)


@router.callback_query(AdminProductCB.filter(F.action == "list"))
async def products_list_cb(callback: CallbackQuery, session: AsyncSession) -> None:
    products = ProductRepository(session)
    all_products = await products.list_all()
    visible = [p for p in all_products if p.is_visible]
    archived = [p for p in all_products if not p.is_visible]
    text = (
        f"\U0001F6CD️ <b>Mahsulotlar</b> — {len(visible)} ta faol"
        + (f", {len(archived)} ta arxivda" if archived else "")
    )
    await callback.message.edit_text(text, reply_markup=admin_products_list_kb(visible, len(archived)))
    await callback.answer()


@router.callback_query(AdminProductCB.filter(F.action == "archive"))
async def products_archive(callback: CallbackQuery, session: AsyncSession) -> None:
    """Hidden products live here instead of mixed into the working list.

    Note a product with order history can never be fully deleted (its
    orders reference it), so "archived" is the real end state for anything
    that has ever sold — this screen is where those go."""
    archived = [p for p in await ProductRepository(session).list_all() if not p.is_visible]
    if not archived:
        await callback.answer("Arxiv bo'sh.", show_alert=True)
        return
    await callback.message.edit_text(
        "\U0001F5C4️ <b>Arxiv — yashirilgan mahsulotlar</b>\n\n"
        "Bu mahsulotlar mijozlarga ko'rinmaydi. Buyurtma tarixi bor mahsulotni butunlay "
        "o'chirib bo'lmaydi (eski buyurtmalar buzilib ketadi) — shuning uchun ular shu yerda saqlanadi.\n\n"
        "Qaytarish uchun mahsulotni ochib «\U0001F441 Ro'yxatga qaytarish» ni bosing.",
        reply_markup=admin_products_archive_kb(archived),
    )
    await callback.answer()


@router.callback_query(AdminProductCB.filter(F.action == "group"))
async def product_group(callback: CallbackQuery, callback_data: AdminProductCB, session: AsyncSession) -> None:
    product = await ProductRepository(session).get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    text, kb = render_product_group(product, callback_data.field or "root")
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(AdminProductCB.filter(F.action == "open"))
async def product_open(callback: CallbackQuery, callback_data: AdminProductCB, session: AsyncSession) -> None:
    product = await ProductRepository(session).get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    text, kb = render_product_group(product, "root")
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(AdminProductCB.filter(F.action == "add"))
async def product_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(panel_chat_id=callback.message.chat.id, panel_message_id=callback.message.message_id, action="new_product_name")
    await show(callback, "Yangi mahsulot nomini yozing:")
    await callback.answer()


@router.callback_query(AdminProductCB.filter(F.action == "edit_field"))
async def product_edit_field(callback: CallbackQuery, callback_data: AdminProductCB, state: FSMContext) -> None:
    field = callback_data.field
    if field == "image":
        await state.set_state(AdminInput.waiting_image)
        await state.update_data(panel_chat_id=callback.message.chat.id, panel_message_id=callback.message.message_id, action="edit_product_field", product_id=callback_data.product_id, field=field)
        await show(callback, "Yangi rasmni yuboring:")
        await callback.answer()
        return

    prompt = FIELD_PROMPTS.get(field, "Yangi qiymatni yozing:")
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(panel_chat_id=callback.message.chat.id, panel_message_id=callback.message.message_id, action="edit_product_field", product_id=callback_data.product_id, field=field)
    await show(callback, prompt)
    await callback.answer()


@router.callback_query(AdminProductCB.filter(F.action == "pick_lang_field"))
async def product_pick_lang_field(callback: CallbackQuery, callback_data: AdminProductCB) -> None:
    await callback.message.edit_reply_markup(
        reply_markup=product_lang_pick_kb(
            callback_data.product_id, callback_data.field, _group_of_lang_field(callback_data.field)
        )
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

    # Provider selection is its own explicit step now (the "Provider"
    # button -> provider_kb picker), not auto-chained from here — chaining
    # used to open a text prompt and then immediately overwrite it with the
    # group screen in the same breath, so the prompt was never actually
    # visible long enough to use.
    text, kb = render_product_group(product, "delivery")
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer("Yetkazish rejimi yangilandi ✅")


_MAX_SUPPLIER_ITEMS = 30


def _supplier_products_kb_and_text(product, items: list) -> tuple[str, object]:
    """Text + keyboard listing a supplier's catalog, so the admin can tap
    to set `external_product_id` instead of typing an id from memory (and
    can actually see stock/name while choosing, not just a bare code)."""
    shown = items[:_MAX_SUPPLIER_ITEMS]
    lines = [
        f"\U0001F4CB <b>Ta'minotchi mahsulotlari</b> ({len(items)} ta)",
        "",
        "Kerakli mahsulotni tanlang — Tashqi ID avtomatik o'rnatiladi:",
    ]
    if len(items) > _MAX_SUPPLIER_ITEMS:
        lines.append(
            f"\n⚠️ Faqat birinchi {_MAX_SUPPLIER_ITEMS} tasi ko'rsatilmoqda. Kerakli mahsulot "
            f"ro'yxatda bo'lmasa, Tashqi ID'ni qo'lda kiriting."
        )

    rows = []
    for item in shown:
        parts = [item.name or item.id]
        if item.stock is not None:
            parts.append(f"(qoldiq: {item.stock})")
        text = " ".join(parts)
        if len(text) > 60:
            text = text[:59] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=AdminProductCB(
                        action="pick_supplier_product", product_id=product.id, field=item.id
                    ).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="✏️ Qo'lda kiritish",
                callback_data=AdminProductCB(action="edit_field", product_id=product.id, field="external_product_id").pack(),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="\U0001F519 Orqaga",
                callback_data=AdminProductCB(action="group", product_id=product.id, field="delivery").pack(),
            )
        ]
    )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(AdminProductCB.filter(F.action == "set_provider"))
async def product_set_provider(callback: CallbackQuery, callback_data: AdminProductCB) -> None:
    from app.keyboards.admin_kb import provider_kb

    await callback.message.edit_reply_markup(reply_markup=provider_kb(callback_data.product_id))
    await callback.answer()


@router.callback_query(AdminProductCB.filter(F.action == "apply_provider"))
async def product_apply_provider(
    callback: CallbackQuery, callback_data: AdminProductCB, session: AsyncSession
) -> None:
    products = ProductRepository(session)
    product = await products.get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    await products.update(product, provider_key=callback_data.field)
    admin_actions_logger.info(
        "product_provider_set id=%s provider=%s admin=%s", product.id, callback_data.field, callback.from_user.id
    )

    # Jump straight into browsing that supplier's catalog when it supports
    # one, instead of leaving the admin to type an id from memory.
    from app.services.providers.registry import get_provider

    provider = get_provider(callback_data.field)
    items = await provider.list_products() if provider else None
    if items:
        text, kb = _supplier_products_kb_and_text(product, items)
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer("Provider saqlandi ✅")
        return

    text, kb = render_product_group(product, "delivery")
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer("Provider saqlandi ✅")


@router.callback_query(AdminProductCB.filter(F.action == "browse_supplier"))
async def product_browse_supplier(
    callback: CallbackQuery, callback_data: AdminProductCB, session: AsyncSession
) -> None:
    product = await ProductRepository(session).get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    if not product.provider_key:
        await callback.answer("Avval Provider tanlang.", show_alert=True)
        return

    from app.services.providers.registry import get_provider

    provider = get_provider(product.provider_key)
    if provider is None:
        await callback.answer("Noma'lum provider.", show_alert=True)
        return

    await callback.answer("Yuklanmoqda…")
    items = await provider.list_products()
    if items is None:
        await show(
            callback,
            "❌ Bu provider ro'yxat berish imkoniyatiga ega emas, yoki ulanish sozlanmagan "
            "(kalit/manzilni Sozlamalar bo'limida tekshiring). Tashqi ID'ni qo'lda kiriting.",
        )
        return
    if not items:
        await show(callback, "ℹ️ Ta'minotchida hozircha mahsulot topilmadi (yoki barchasi tugagan).")
        return
    text, kb = _supplier_products_kb_and_text(product, items)
    await show(callback, text, reply_markup=kb)


@router.callback_query(AdminProductCB.filter(F.action == "pick_supplier_product"))
async def product_pick_supplier_product(
    callback: CallbackQuery, callback_data: AdminProductCB, session: AsyncSession
) -> None:
    products = ProductRepository(session)
    product = await products.get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    await products.update(product, external_product_id=callback_data.field)
    admin_actions_logger.info(
        "product_external_id_picked id=%s ext_id=%s admin=%s", product.id, callback_data.field, callback.from_user.id
    )
    text, kb = render_product_group(product, "delivery")
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer("Tashqi ID o'rnatildi ✅")


@router.callback_query(AdminProductCB.filter(F.action == "toggle_field"))
async def product_toggle_field(
    callback: CallbackQuery, callback_data: AdminProductCB, session: AsyncSession
) -> None:
    """One handler for every boolean on a product (visibility, referral
    eligibility, auto-card, manual-confirm) instead of four near-identical
    ones.

    `field` comes straight off a callback, so it is checked against an
    explicit whitelist — otherwise a hand-crafted callback could flip any
    column on the row.
    """
    field = callback_data.field or ""
    if field not in TOGGLEABLE_FIELDS:
        await callback.answer("Noma'lum sozlama.", show_alert=True)
        return

    products = ProductRepository(session)
    product = await products.get_by_id(callback_data.product_id)
    if product is None:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return

    new_value = not getattr(product, field, False)
    await products.update(product, **{field: new_value})
    admin_actions_logger.info(
        "product_toggled id=%s field=%s value=%s admin=%s",
        product.id, field, new_value, callback.from_user.id,
    )

    # Re-render whichever group the button lives in, so its value line
    # updates too. Visibility lives on the root screen.
    group = "root"
    for name, spec in PRODUCT_GROUPS.items():
        if any(k == "toggle" and key == field for k, key, _ in spec["items"]):
            group = name
            break
    text, kb = render_product_group(product, group)
    await callback.message.edit_text(text, reply_markup=kb)

    if field == "is_visible":
        await callback.answer("Ro'yxatga qaytarildi ✅" if new_value else "Arxivga yashirildi \U0001F5C4️")
    else:
        await callback.answer("Yoqildi ✅" if new_value else "O'chirildi")


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
    deleted = await products.delete(product)
    if deleted:
        admin_actions_logger.info(
            "product_deleted id=%s name=%s admin=%s", product.id, product.name, callback.from_user.id
        )
        all_products = await products.list_all()
        visible = [x for x in all_products if x.is_visible]
        archived = [x for x in all_products if not x.is_visible]
        await callback.message.edit_text(
            "✅ Mahsulot butunlay o'chirildi.",
            reply_markup=admin_products_list_kb(visible, len(archived)),
        )
        await callback.answer()
        return

    # Database refused: this product has existing orders (RESTRICT FK) —
    # deleting it outright would break those orders' history. Hide it
    # instead, which is what the admin actually wants in practice (get it
    # out of the shop) without losing past sales data.
    await products.set_visibility(product, False)
    admin_actions_logger.info(
        "product_hidden_instead_of_deleted id=%s name=%s admin=%s", product.id, product.name, callback.from_user.id
    )
    await callback.message.edit_text(
        "⚠️ Bu mahsulot bo'yicha oldin buyurtmalar bo'lgani uchun butunlay o'chirib bo'lmadi "
        "(buyurtmalar tarixi buzilmasligi uchun himoyalangan).\n\n"
        "\U0001F5C4️ Shuning uchun uni <b>arxivga yashirdik</b> — endi do'konda mijozlarga ko'rinmaydi, "
        "lekin eski buyurtmalar va statistikada saqlanib qoladi.\n\n"
        "Uni «\U0001F5C4️ Arxiv» bo'limida topasiz.",
        reply_markup=admin_products_list_kb(
            [x for x in await products.list_all() if x.is_visible],
            len([x for x in await products.list_all() if not x.is_visible]),
        ),
    )
    await callback.answer()
