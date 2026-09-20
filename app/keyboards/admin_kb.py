from __future__ import annotations

from aiogram.types import (
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)

from app.database.models import Product
from app.database.models.enums import DeliveryMode
from app.keyboards.base_buttons import InlineKeyboardButton, KeyboardButton
from app.keyboards.callback_data import (
    AdminBroadcastCB,
    AdminButtonCB,
    AdminInventoryCB,
    AdminOrderListCB,
    AdminPhoneCB,
    AdminProductCB,
    AdminReferralRedemptionCB,
    AdminReferralRewardCB,
    AdminReferralWithdrawCB,
    AdminSettingsCB,
    AdminStockWaitersCB,
    AdminUserCB,
    ConfirmCB,
    OrderCB,
)
from app.utils.formatting import fmt_price, product_button_emoji_prefix

ADMIN_BTN_PRODUCTS = "\U0001F6CD️ Mahsulotlar"
ADMIN_BTN_ORDERS = "\U0001F4E5 Buyurtmalar"
ADMIN_BTN_STATS = "\U0001F4CA Statistika"
ADMIN_BTN_SETTINGS = "⚙️ Sozlamalar"
ADMIN_BTN_BROADCAST = "\U0001F4E2 Xabar yuborish"
ADMIN_BTN_USERS = "\U0001F464 Foydalanuvchilar"
ADMIN_BTN_EXIT = "\U0001F6AA Admin paneldan chiqish"


def admin_main_menu_kb() -> ReplyKeyboardMarkup:
    # Referral do'koni no longer gets its own row — it now lives inside
    # Sozlamalar -> Referal dasturi, alongside the rest of the referral
    # program's settings, instead of sitting apart from them.
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ADMIN_BTN_PRODUCTS), KeyboardButton(text=ADMIN_BTN_ORDERS)],
            [KeyboardButton(text=ADMIN_BTN_STATS), KeyboardButton(text=ADMIN_BTN_SETTINGS)],
            [KeyboardButton(text=ADMIN_BTN_BROADCAST), KeyboardButton(text=ADMIN_BTN_USERS)],
            [KeyboardButton(text=ADMIN_BTN_EXIT)],
        ],
        resize_keyboard=True,
    )


# ----------------------------------------------------------------------
# Product editor — grouped, same data-driven pattern as SETTINGS_GROUPS.
#
# The old screen was one flat wall of ~16 button rows with no ordering
# logic, which made finding anything a hunt. PRODUCT_GROUPS is the single
# source of truth for both the buttons and the "current values" summary
# (see app/handlers/admin/products.py:render_product_group).
#
# Item kinds:
#   ("field", attr, label)   -> free-text edit of that column
#   ("lang",  base, label)   -> per-language edit (base_uz/_ru/_en)
#   ("image", None, label)   -> photo upload
#   ("toggle", attr, label)  -> boolean flip (attr MUST be in TOGGLEABLE_FIELDS)
#   ("mode",  None, label)   -> delivery-mode picker
#   ("inventory", None, label)
#   ("group", name, label)   -> open a subgroup
#   ("api_only", ...)        -> only rendered for API-delivery products
# ----------------------------------------------------------------------

# Whitelist for the generic toggle handler. Without this a crafted
# callback could flip *any* column on the product row, so the set is
# explicit rather than derived.
TOGGLEABLE_FIELDS = {
    "is_visible",
    "referral_eligible",
    "card_auto_enabled",
    "card_manual_enabled",
    "card_manual_confirm",
    "referral_reward_by_qty",
}

PRODUCT_GROUPS: dict[str, dict] = {
    "root": {
        "title": "\U0001F6CD️ <b>Mahsulot sozlamalari</b>",
        "intro": "Kerakli bo'limni tanlang:",
        "items": [
            ("group", "basic", "\U0001F4DD Asosiy ma'lumot"),
            ("group", "prices", "\U0001F4B0 Narxlar"),
            ("group", "delivery", "\U0001F4E6 Yetkazib berish"),
            ("group", "payment", "\U0001F4B3 To'lov usullari"),
            ("group", "limits", "\U0001F522 Limit va referral"),
            ("inventory", None, "\U0001F4E6 Inventar (kodlar)"),
        ],
    },
    "basic": {
        "title": "\U0001F4DD <b>Asosiy ma'lumot</b>",
        "intro": "Nomi va tavsifi har bir tilga alohida yozilishi mumkin. Til bo'yicha yozilmasa, standart qiymat ishlatiladi.",
        "parent": "root",
        "items": [
            ("field", "name", "✏️ Nomi (standart)"),
            ("field", "emoji", "\U0001F3F7️ Emoji"),
            ("field", "description", "\U0001F4C4 Tavsifi (standart)"),
            ("lang", "name", "\U0001F310 Nomi (til bo'yicha)"),
            ("lang", "description", "\U0001F310 Tavsifi (til bo'yicha)"),
            ("image", None, "\U0001F5BC️ Rasm"),
        ],
    },
    "prices": {
        "title": "\U0001F4B0 <b>Narxlar</b>",
        "intro": (
            "Har bir to'lov usuli o'z narxini talab qiladi:\n"
            "• UZS — karta orqali to'lov uchun (majburiy)\n"
            "• USD — kripto to'lov uchun (bo'sh bo'lsa, kripto tugmasi chiqmaydi)\n"
            "• Stars — Telegram Stars uchun (bo'sh bo'lsa, Stars tugmasi chiqmaydi)"
        ),
        "parent": "root",
        "items": [
            ("field", "price", "\U0001F4B5 Narx (UZS)"),
            ("field", "price_usd", "\U0001FA99 Narx (USD / kripto)"),
            ("field", "price_stars", "⭐ Narx (Stars)"),
        ],
    },
    "delivery": {
        "title": "\U0001F4E6 <b>Yetkazib berish</b>",
        "intro": (
            "Uch rejim bor: ichki inventar (tayyor kodlar), qo'lda (o'zingiz yozasiz), "
            "tashqi API (ta'minotchidan avtomatik olinadi).\n"
            "Provider va Tashqi ID faqat API rejimida ko'rinadi.\n\n"
            "\U0001F511 <b>Provider</b> — ro'yxatdan tanlanadi (Sozlamalar -> Reseller/Shamekh API'da "
            "kalit va manzil sozlanadi, bu yerda faqat qaysi biri shu mahsulotga xizmat qilishini "
            "tanlaysiz).\n"
            "\U0001F194 <b>Tashqi ID</b> — ta'minotchining o'z kataloridagi shu mahsulot raqami/kodi. "
            "\U0001F4CB tugmasi orqali ta'minotchi kataloridan to'g'ridan-to'g'ri tanlash mumkin "
            "(qo'lda yozishga hojat qolmaydi, agar provider shuni qo'llab-quvvatlasa)."
        ),
        "parent": "root",
        "items": [
            ("mode", None, "\U0001F504 Yetkazish rejimi"),
            ("provider_picker", None, "\U0001F511 Provider"),
            ("api_only_field", "external_product_id", "\U0001F194 Tashqi ID"),
            ("browse_supplier", None, "\U0001F4CB Ta'minotchi mahsulotlarini ko'rish"),
            ("lang", "delivery_instructions", "\U0001F310 Yetkazishdan keyingi xabar"),
        ],
    },
    "payment": {
        "title": "\U0001F4B3 <b>To'lov usullari</b>",
        "intro": (
            "⚡️ <b>Avto karta</b> — mijoz noyob summa o'tkazadi, bot CardXabar orqali o'zi tanaydi.\n"
            "\U0001F512 <b>Qo'lda tasdiqlash</b> — to'lov to'g'ri kelsa ham, yetkazishdan oldin sizdan "
            "tugma bosishni kutadi. Qimmat mahsulotlar uchun."
        ),
        "parent": "root",
        "items": [
            ("field", "payment_instructions", "\U0001F4B3 To'lov ma'lumoti (shu mahsulot uchun)"),
            ("toggle", "card_auto_enabled", "⚡️ Avto karta to'lovi"),
            ("toggle", "card_manual_enabled", "\U0001F9FE Chek yuborib to'lash"),
            ("toggle", "card_manual_confirm", "\U0001F512 Qo'lda tasdiqlash"),
        ],
    },
    "limits": {
        "title": "\U0001F522 <b>Limit va referral</b>",
        "intro": (
            "Max. soni 1 dan katta bo'lsa, mijozga miqdor tanlash oynasi chiqadi.\n"
            "Tartib raqami kichik bo'lsa, mahsulot ro'yxatda yuqorida turadi.\n\n"
            "\U0001F91D Referral mukofoti yoqilgan bo'lsa, mahsulotga o'ziga xos summa/foiz qo'yish "
            "mumkin — bo'sh qoldirilsa, umumiy sozlamalardagi (birinchi/keyingi buyurtma) qiymat "
            "ishlatiladi. Foiz kiritilganda (masalan \"2%\"), u narxdan yoki sonidan (necha dona/Stars) "
            "hisoblanishini pastdagi tugma bilan tanlaysiz — Stars kabi donali mahsulotlarda odatda "
            "sonidan hisoblash qulayroq (100 Starsga 2%, ya'ni 2 dona bonus)."
        ),
        "parent": "root",
        "items": [
            ("field", "min_order_qty", "\U0001F53D Min. buyurtma soni"),
            ("field", "max_order_qty", "\U0001F53C Max. buyurtma soni"),
            ("field", "sort_order", "\U0001F500 Tartib raqami"),
            ("toggle", "referral_eligible", "\U0001F91D Referral mukofoti"),
            ("field", "referral_reward_value", "\U0001F4B8 Bonus (summa yoki foiz, masalan 5000 yoki 2%)"),
            ("toggle", "referral_reward_by_qty", "\U0001F522 Foiz sonidan hisoblansin (narx o'rniga)"),
        ],
    },
}


def admin_products_list_kb(products: list[Product], archived_count: int = 0) -> InlineKeyboardMarkup:
    """Main product list — visible products only. Hidden/archived ones live
    behind their own button so they stop cluttering the working list."""
    rows = []
    for p in products:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{product_button_emoji_prefix(p)}{p.name} — {fmt_price(float(p.price))}",
                    icon_custom_emoji_id=getattr(p, "custom_emoji_id", None),
                    callback_data=AdminProductCB(action="open", product_id=p.id).pack(),
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="➕ Yangi mahsulot", callback_data=AdminProductCB(action="add").pack())]
    )
    if archived_count:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"\U0001F5C4️ Arxiv — yashirilganlar ({archived_count})",
                    callback_data=AdminProductCB(action="archive").pack(),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_products_archive_kb(products: list[Product]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"⚪ {product_button_emoji_prefix(p)}{p.name}",
                icon_custom_emoji_id=getattr(p, "custom_emoji_id", None),
                callback_data=AdminProductCB(action="open", product_id=p.id).pack(),
            )
        ]
        for p in products
    ]
    rows.append(
        [InlineKeyboardButton(text="\U0001F519 Faol mahsulotlar", callback_data=AdminProductCB(action="list").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_product_detail_kb(product: Product, group: str = "root") -> InlineKeyboardMarkup:
    spec = PRODUCT_GROUPS.get(group) or PRODUCT_GROUPS["root"]
    pid = product.id
    rows: list[list[InlineKeyboardButton]] = []

    def cb(action: str, field: str = "") -> str:
        return AdminProductCB(action=action, product_id=pid, field=field).pack()

    for kind, key, label in spec["items"]:
        if kind == "group":
            rows.append([InlineKeyboardButton(text=label, callback_data=cb("group", key))])
        elif kind == "field":
            rows.append([InlineKeyboardButton(text=label, callback_data=cb("edit_field", key))])
        elif kind == "api_only_field":
            if product.delivery_mode == DeliveryMode.API:
                rows.append([InlineKeyboardButton(text=label, callback_data=cb("edit_field", key))])
        elif kind == "provider_picker":
            if product.delivery_mode == DeliveryMode.API:
                rows.append([InlineKeyboardButton(text=label, callback_data=cb("set_provider"))])
        elif kind == "browse_supplier":
            if product.delivery_mode == DeliveryMode.API and product.provider_key:
                rows.append([InlineKeyboardButton(text=label, callback_data=cb("browse_supplier"))])
        elif kind == "lang":
            rows.append([InlineKeyboardButton(text=label, callback_data=cb("pick_lang_field", key))])
        elif kind == "image":
            rows.append([InlineKeyboardButton(text=label, callback_data=cb("edit_field", "image"))])
        elif kind == "mode":
            rows.append([InlineKeyboardButton(text=label, callback_data=cb("set_mode"))])
        elif kind == "inventory":
            rows.append(
                [InlineKeyboardButton(text=label, callback_data=AdminInventoryCB(action="menu", product_id=pid).pack())]
            )
        elif kind == "toggle":
            state = "✅" if getattr(product, key, False) else "❌"
            rows.append([InlineKeyboardButton(text=f"{label}: {state}", callback_data=cb("toggle_field", key))])

    if group == "root":
        visibility_text = (
            "\U0001F5C4️ Arxivga yashirish" if product.is_visible else "\U0001F441 Ro'yxatga qaytarish"
        )
        rows.append(
            [
                InlineKeyboardButton(text=visibility_text, callback_data=cb("toggle_field", "is_visible")),
                InlineKeyboardButton(text="\U0001F5D1️ O'chirish", callback_data=cb("delete")),
            ]
        )
        rows.append(
            [InlineKeyboardButton(text="\U0001F519 Ro'yxatga qaytish", callback_data=AdminProductCB(action="list").pack())]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=cb("group", spec.get("parent", "root")))]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delivery_mode_kb(product_id: int) -> InlineKeyboardMarkup:
    rows = []
    labels = {
        DeliveryMode.INVENTORY: "\U0001F4E6 Ichki inventar",
        DeliveryMode.MANUAL: "✍️ Qo'lda yetkazish",
        DeliveryMode.API: "\U0001F310 Tashqi API",
    }
    for mode, label in labels.items():
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=AdminProductCB(action="apply_mode", product_id=product_id, field=mode.value).pack(),
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminProductCB(action="open", product_id=product_id).pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


_PROVIDER_LABELS = {
    "reseller_api": "\U0001F310 Reseller API",
    "shamekh_api": "\U0001F310 Shamekh API",
    "fragment": "⭐ Fragment (Stars/Premium)",
    "mock_provider": "\U0001F9EA Mock (sinov)",
}


def provider_kb(product_id: int) -> InlineKeyboardMarkup:
    """Pick a registered provider by name instead of typing its key from
    memory — see `app.services.providers.registry.list_provider_keys()`,
    the single source of truth for which providers actually exist."""
    from app.services.providers.registry import list_provider_keys  # local import avoids a cycle

    rows = [
        [
            InlineKeyboardButton(
                text=_PROVIDER_LABELS.get(key, key),
                callback_data=AdminProductCB(action="apply_provider", product_id=product_id, field=key).pack(),
            )
        ]
        for key in list_provider_keys()
    ]
    rows.append(
        [InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminProductCB(action="open", product_id=product_id).pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_product_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=AdminProductCB(action="confirm_delete", product_id=product_id).pack()),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data=AdminProductCB(action="open", product_id=product_id).pack()),
            ]
        ]
    )


def admin_inventory_menu_kb(product_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="➕ Bitta kod qo'shish", callback_data=AdminInventoryCB(action="add_one", product_id=product_id).pack())],
        [InlineKeyboardButton(text="\U0001F4E5 Ko'p kod import qilish", callback_data=AdminInventoryCB(action="bulk", product_id=product_id).pack())],
        [InlineKeyboardButton(text="\U0001F4CB Kodlarni ko'rish", callback_data=AdminInventoryCB(action="view", product_id=product_id).pack())],
        [InlineKeyboardButton(text="\U0001F5D1️ Kod o'chirish", callback_data=AdminInventoryCB(action="pick_delete", product_id=product_id).pack())],
        [InlineKeyboardButton(text="\U0001F4E4 Eksport qilish", callback_data=AdminInventoryCB(action="export", product_id=product_id).pack())],
        [InlineKeyboardButton(text="\U0001F514 Kutayotganlar", callback_data=AdminStockWaitersCB(action="list", product_id=product_id).pack())],
        [InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminProductCB(action="open", product_id=product_id).pack())],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_stock_waiters_kb(product_id: int, has_waiters: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_waiters:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📢 Kelganini xabar berish",
                    callback_data=AdminStockWaitersCB(action="notify_all", product_id=product_id).pack(),
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminInventoryCB(action="menu", product_id=product_id).pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inventory_delete_pick_kb(product_id: int, codes: list, selected_ids: set[int] | None = None) -> InlineKeyboardMarkup:
    """One toggle button per unused code (checkbox-style multi-select), plus
    a row to delete just the selected ones or wipe everything at once."""
    selected_ids = selected_ids or set()
    rows = []
    for c in codes:
        label = c.code if len(c.code) <= 40 else c.code[:37] + "..."
        mark = "✅" if c.id in selected_ids else "⬜"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {label}",
                    callback_data=AdminInventoryCB(action="toggle_select", product_id=product_id, code_id=c.id).pack(),
                )
            ]
        )
    if selected_ids:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"\U0001F5D1️ Tanlanganlarni o'chirish ({len(selected_ids)})",
                    callback_data=AdminInventoryCB(action="delete_selected", product_id=product_id).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="\U0001F4A5 Barchasini o'chirish",
                callback_data=AdminInventoryCB(action="delete_all", product_id=product_id).pack(),
            )
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminInventoryCB(action="menu", product_id=product_id).pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inventory_delete_confirm_kb(product_id: int, action: str) -> InlineKeyboardMarkup:
    """Generic Ha/Yo'q confirm for the bulk-delete actions (`confirm_selected`
    / `confirm_all`); "Yo'q" goes back to the picker so nothing is lost."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Ha, o'chirish",
                    callback_data=AdminInventoryCB(action=action, product_id=product_id).pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data=AdminInventoryCB(action="pick_delete", product_id=product_id).pack(),
                ),
            ]
        ]
    )


def admin_orders_list_kb(
    orders, status_key: str, page: int, total: int, per_page: int
) -> InlineKeyboardMarkup:
    """One row per order + pager, all inside a single screen.

    The old list sent one message per order — fifty taps of scrolling for a
    busy day, and every one of those messages kept live buttons long after
    the order moved on. Here the list is one message: paging replaces it,
    opening an order replaces it, and coming back replaces it again.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for order in orders:
        who = order.user.username or order.user.telegram_id if order.user else "-"
        name = (order.product.name if order.product else "-")[:22]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"#{order.id} · {name} · @{who}",
                    callback_data=AdminOrderListCB(
                        action="open", order_id=order.id, page=page
                    ).pack(),
                )
            ]
        )

    pages = max(1, (total + per_page - 1) // per_page)
    if pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=AdminOrderListCB(action=status_key, page=page - 1).pack()
                )
            )
        nav.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{pages}", callback_data=AdminOrderListCB(action="noop").pack()
            )
        )
        if page < pages - 1:
            nav.append(
                InlineKeyboardButton(
                    text="▶️", callback_data=AdminOrderListCB(action=status_key, page=page + 1).pack()
                )
            )
        rows.append(nav)

    if status_key == "failed" and orders:
        rows.append(
            [
                InlineKeyboardButton(
                    text="\U0001F501 Hammasini qayta urinish",
                    callback_data=AdminOrderListCB(action="retry_all", page=page).pack(),
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="‹ Orqaga", callback_data=AdminOrderListCB(action="menu").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_orders_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="⏳ Kutilayotgan", callback_data=AdminOrderListCB(action="pending").pack())],
        [InlineKeyboardButton(text="✅ Tasdiqlangan", callback_data=AdminOrderListCB(action="approved").pack())],
        [InlineKeyboardButton(text="📦 Yetkazilgan", callback_data=AdminOrderListCB(action="delivered").pack())],
        [InlineKeyboardButton(text="⚠️ Yetkazilmagan", callback_data=AdminOrderListCB(action="failed").pack())],
        [InlineKeyboardButton(text="❌ Rad etilgan", callback_data=AdminOrderListCB(action="rejected").pack())],
        [InlineKeyboardButton(text="\U0001F50D ID orqali qidirish", callback_data=AdminOrderListCB(action="search").pack())],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_order_detail_kb(order, src: str | None = None, page: int = 0) -> InlineKeyboardMarkup:
    """Actions available on a single looked-up order. Which ones appear
    depends on where the order currently is, so the admin can't e.g. try to
    approve something already delivered."""
    from app.database.models.enums import OrderStatus

    rows: list[list[InlineKeyboardButton]] = []
    oid = order.id

    undecided = {
        OrderStatus.AWAITING_PROOF,
        OrderStatus.AWAITING_CRYPTO_PAYMENT,
        OrderStatus.AWAITING_STARS_PAYMENT,
        OrderStatus.AWAITING_CARD_PAYMENT,
        OrderStatus.PENDING_APPROVAL,
    }
    if order.status in undecided:
        rows.append(
            [
                InlineKeyboardButton(text="✅ Tasdiqlash va yetkazish", callback_data=OrderCB(action="approve", order_id=oid, src=src, page=page).pack()),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=OrderCB(action="reject", order_id=oid, src=src, page=page).pack()),
            ]
        )
    if order.status in (OrderStatus.APPROVED, OrderStatus.FAILED):
        # Retry first: when the cause was a flat wallet or stale cookies,
        # one tap after topping up is the whole fix.
        rows.append(
            [
                InlineKeyboardButton(
                    text="\U0001F501 Avtomatik qayta urinish",
                    callback_data=OrderCB(action="retry_auto", order_id=oid, src=src, page=page).pack(),
                )
            ]
        )
        rows.append(
            [InlineKeyboardButton(text="✍️ Qo'lda yuborish", callback_data=OrderCB(action="write_manual", order_id=oid, src=src, page=page).pack())]
        )
    back_cb = (
        AdminOrderListCB(action=src, page=page).pack()
        if src
        else AdminOrderListCB(action="menu").pack()
    )
    if order.user is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✉️ Mijozga xabar yozish",
                    callback_data=AdminUserCB(action="message", user_id=order.user.id).pack(),
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="\U0001F464 Mijoz profili",
                    callback_data=AdminUserCB(action="profile", user_id=order.user.id).pack(),
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="\U0001F50D Boshqa buyurtma qidirish", callback_data=AdminOrderListCB(action="search").pack())]
    )
    rows.append([InlineKeyboardButton(text="‹ Orqaga", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_order_action_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=OrderCB(action="approve", order_id=order_id).pack()),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=OrderCB(action="reject", order_id=order_id).pack()),
            ]
        ]
    )


def admin_card_confirm_kb(order_id: int) -> InlineKeyboardMarkup:
    """Shown when a card payment matched but delivery is held for a human —
    either because global auto-delivery is off, or the product is flagged
    manual-confirm."""
    from app.keyboards.callback_data import CardAutoCB  # local import avoids a cycle

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Yetkazish",
                    callback_data=CardAutoCB(action="admin_confirm", order_id=order_id).pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish",
                    callback_data=CardAutoCB(action="admin_reject", order_id=order_id).pack(),
                ),
            ]
        ]
    )


def admin_retry_all_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="\U0001F501 Hammasini qayta urinish",
                    callback_data=AdminOrderListCB(action="retry_all").pack(),
                )
            ]
        ]
    )


def admin_write_manual_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="\U0001F501 Avtomatik qayta urinish",
                    callback_data=OrderCB(action="retry_auto", order_id=order_id).pack(),
                )
            ],
            [InlineKeyboardButton(text="✍️ Xabar yozish", callback_data=OrderCB(action="write_manual", order_id=order_id).pack())]
        ]
    )


# ----------------------------------------------------------------------
# Settings menu — one grouped, navigable tree instead of the ~30-button
# flat wall it used to be.
#
# SETTINGS_GROUPS is the single source of truth: both the keyboard builder
# (`admin_settings_menu_kb`) and the "here are your current values" summary
# renderer (`app/handlers/admin/settings.py:render_settings_group`) read
# from it, so a setting can never appear in one and be missing from the
# other. Adding a new setting = adding one line here.
#
# Item kinds:
#   ("toggle", key, label)  -> on/off switch
#   ("edit",   key, label)  -> free-text value
#   ("masked", key, label)  -> secret, only last 4 chars ever displayed
#   ("lang",   base, label) -> per-language text (base_uz/_ru/_en)
#   ("group",  name, label) -> opens another group below
#   ("phones", None, label) -> the allowed-foreign-numbers list screen
#   ("test_reseller", None, label) -> live connection check, not a value
#   ("test_fragment", None, label) -> same, for the Fragment wallet/session
# ----------------------------------------------------------------------

SETTINGS_GROUPS: dict[str, dict] = {
    "root": {
        "title": "⚙️ <b>Sozlamalar</b>",
        "intro": "Kerakli bo'limni tanlang:",
        "items": [
            ("group", "texts", "\U0001F4DD Matnlar va xabarlar"),
            ("group", "delivery", "\U0001F4E6 Yetkazib berish"),
            ("group", "payments", "\U0001F4B3 To'lov usullari"),
            ("group", "referral", "\U0001F91D Referal dasturi"),
            ("button_manager", None, "\U0001F3A8 Tugmalar boshqaruvi"),
            ("group", "access", "\U0001F512 Kirish nazorati"),
            ("group", "reseller", "\U0001F310 Reseller API"),
            ("group", "shamekh", "\U0001F310 Shamekh API"),
            ("group", "fragment", "⭐ Fragment (Stars/Premium)"),
        ],
    },
    "texts": {
        "title": "\U0001F4DD <b>Matnlar va xabarlar</b>",
        "intro": "Har biri UZ/RU/EN uchun alohida yoziladi. Matn uzun bo'lsa .txt fayl yuborsangiz ham bo'ladi.",
        "parent": "root",
        "items": [
            ("lang", "welcome_message", "\U0001F44B Xush kelibsiz xabari"),
            ("lang", "support_message", "\U0001F4AC Yordam xabari"),
            ("lang", "payment_instructions", "\U0001F4B3 Umumiy to'lov ma'lumoti"),
            ("lang", "reviews_text", "⭐ Sharhlar matni"),
            ("edit", "proof_channel_url", "📢 Isbotlar kanali havolasi"),
        ],
    },
    "delivery": {
        "title": "\U0001F4E6 <b>Yetkazib berish</b>",
        "intro": "Qaysi yetkazish usullari ishlashi va oldindan buyurtma qabul qilinishi.",
        "parent": "root",
        "items": [
            ("toggle", "automatic_delivery_enabled", "\U0001F504 Avto-yetkazish (inventar)"),
            ("toggle", "manual_delivery_enabled", "✍️ Qo'lda yetkazish"),
            ("toggle", "api_delivery_enabled", "\U0001F310 API orqali yetkazish"),
            ("toggle", "preorder_enabled", "\U0001F4E6 Oldindan buyurtma"),
        ],
    },
    "payments": {
        "title": "\U0001F4B3 <b>To'lov usullari</b>",
        "intro": (
            "Karta orqali to'lov doim ishlaydi (chek/skrinshot bilan).\n"
            "Kripto to'lov uchun mahsulotga USD narx, Stars uchun Stars narxi kiritilgan bo'lishi kerak.\n\n"
            "⚠️ <b>Karta raqami</b> — mijozlar shu kartaga to'laydi. Uning oxirgi 4 raqami "
            "tekshiruv uchun ham ishlatiladi: boshqa kartangizga tushgan pul buyurtmani yopmaydi.\n"
            "⚠️ <b>Karta hisobi ulanishi</b> — avtomatik karta tekshiruvi uchun. "
            "Faqat shu ulanishdan kelgan CardXabar xabarlari hisobga olinadi. "
            "Bo'sh bo'lsa, avtomatik tekshiruv umuman ishlamaydi."
        ),
        "parent": "root",
        "items": [
            ("toggle", "crypto_payment_enabled", "\U0001FA99 Kripto to'lov"),
            ("toggle", "stars_payment_enabled", "⭐ Telegram Stars to'lov"),
            ("toggle", "card_payment_enabled", "⚡️ Avtomatik karta to'lovi"),
            ("edit", "card_auto_number", "\U0001F4B3 Karta raqami (to'lov uchun)"),
            ("edit", "card_auto_holder", "\U0001F464 Karta egasi"),
            ("lang", "card_auto_note", "\U0001F4DD Qo'shimcha izoh (ixtiyoriy)"),
            ("toggle", "card_auto_deliver_enabled", "\U0001F680 Avtomatik yetkazish"),
            ("edit", "card_payment_timeout_minutes", "⏱ To'lov kutish (daqiqa)"),
            ("toggle", "card_notify_unmatched", "\U0001F514 Nomos to'lovlar haqida ogohlantirish"),
            ("edit", "card_notify_sender", "\U0001F4B3 Karta xabarchisi (CardXabarBot)"),
            ("edit", "card_business_connection_id", "\U0001F512 Karta hisobi ulanishi"),
        ],
    },
    "referral": {
        "title": "\U0001F91D <b>Referal dasturi</b>",
        "intro": (
            "Bu yerda umumiy qoidalar, Ball (taklif mukofoti) va referal do'koni boshqariladi.\n\n"
            "\U0001F4B5 <b>Xarid mukofoti</b> (taklif qilingan odam xarid qilganda beriladigan summa/foiz) "
            "endi har bir mahsulotning o'zida sozlanadi: Mahsulotlar -> mahsulot -> Limit va referral. "
            "Shu yerda faqat umumiy yoqish/o'chirish qoladi.\n"
            "\U0001F3AF <b>Ball</b> — taklif qilingan odam <b>tasdiqdan o'tganda</b> beriladi (umumiy, "
            "mahsulotga bog'liq emas). Faqat referal do'konida sarflanadi, pul sifatida yechilmaydi."
        ),
        "parent": "root",
        "items": [
            ("toggle", "referral_enabled", "\U0001F91D Referal tizimi (umumiy)"),
            ("edit", "referral_currency", "\U0001F4B1 Valyuta nomi (xarid mukofoti uchun)"),
            ("edit", "referral_withdraw_min", "\U0001F4B0 Min. pul yechish miqdori"),
            (
                "toggle",
                "referral_balance_payment_enabled",
                "\U0001F6D2 Balansdan mahsulot sotib olish (narxni to'liq qoplasa)",
            ),
            ("group", "referral_points", "\U0001F3AF Ball (taklif uchun)"),
            ("lang", "referral_rules", "\U0001F4DC Referal qoidalari matni"),
            ("referral_shop", None, "\U0001F381 Referal do'koni (sovg'alar)"),
        ],
    },
    "referral_points": {
        "title": "\U0001F3AF <b>Ball (taklif mukofoti)</b>",
        "intro": (
            "Taklif qilingan odam telefon+captcha tasdiqlashidan o'tganda beriladi — xarid shart emas.\n"
            "Ball faqat referal do'konida sarflanadi, pul sifatida yechilmaydi.\n"
            "Tasdiqlash botni bloklamaydi: o'tmagan odam ham botdan bemalol foydalanadi, "
            "shunchaki taklif qilgan odamga hisoblanmaydi."
        ),
        "parent": "referral",
        "items": [
            ("edit", "referral_points_name", "\U0001F3F7️ Ball nomi"),
            ("toggle", "referral_confirm_reward_enabled", "\U0001F3AF Taklif mukofoti"),
            ("edit", "referral_confirm_reward_value", "✏️ Har bir tasdiq uchun ball"),
            ("toggle", "referral_verification_enabled", "\U0001F4DE Tasdiqlash (telefon+captcha)"),
        ],
    },
    "access": {
        "title": "\U0001F512 <b>Kirish nazorati</b>",
        "intro": (
            "Yoqilsa, foydalanuvchi botdan foydalanishdan oldin oferta matniga rozilik beradi "
            "va majburiy kanalga obuna bo'ladi. Adminlar bu tekshiruvdan ozod.\n"
            "⚠️ Oferta matni bo'sh bo'lsa, tizim xavfsizlik uchun hech kimni bloklamaydi.\n"
            "⚠️ Bot majburiy kanalda administrator bo'lishi shart.\n\n"
            "📞 Telefon raqami — yoqilsa, HAR BIR foydalanuvchi (nafaqat referal orqali kelganlar) "
            "botdan foydalanishdan oldin raqamini yuborishi shart (faqat Telegram kontakt tugmasi "
            "orqali — o'z shaxsiy raqami, boshqa birovniki emas). Chet el raqami ruxsat etilganlar "
            "ro'yxatida bo'lmasa, bot bloklanmaydi — faqat referal hisoblanmaydi, deb ogohlantiriladi.\n\n"
            "\U0001F4CB Log kanal — sozlansa, faqat YANGI BUYURTMA yozuvlari (mijoz, mahsulot, to'lov, "
            "vaqt) shu yerga tushadi — toza buyurtmalar tarixi sifatida. Yordam so'rovlari, referal "
            "pul yechish/sovg'a so'rovlari va qo'lda tasdiqlash kerak bo'lgan buyurtmalar har doim "
            "sizning shaxsiy chatingizga (botga) kelaveradi — bu muhim xabarlar tarix ichida yo'qolib "
            "ketmasligi uchun."
        ),
        "parent": "root",
        "items": [
            ("toggle", "onboarding_gate_enabled", "\U0001F6AA Majburiy oferta + kanal"),
            ("lang", "oferta_text", "\U0001F4C4 Oferta matni"),
            ("edit", "required_channel", "\U0001F4E2 Majburiy kanal (@username/ID)"),
            ("edit", "required_channel_url", "\U0001F517 Kanal havolasi (join link)"),
            ("toggle", "phone_gate_enabled", "\U0001F4DE Majburiy telefon raqami"),
            ("phones", None, "☎️ Ruxsat etilgan chet el raqamlari"),
            ("edit", "log_channel_id", "\U0001F4CB Log kanal — buyurtmalar tarixi (@username/ID)"),
        ],
    },
    "fragment": {
        "title": "⭐ <b>Fragment (Stars / Premium)</b>",
        "intro": (
            "Telegram Stars va Premium'ni Fragment.com orqali avtomatik yetkazish.\n\n"
            "⚠️ <b>Seed ibora</b> — faqat shu ish uchun ochilgan <b>alohida hamyon</b>dan foydalaning "
            "va unda kichik ishchi summa ushlang. Seed hech qayoqqa yuborilmaydi: kalit shu serverda "
            "hosil qilinadi va tranzaksiya shu yerda imzolanadi.\n"
            "⚠️ <b>Cookie'lar eskiradi.</b> Yetkazish \"kirish\" xatosi bilan to'xtasa, ularni yangilang.\n\n"
            "Mahsulotda Tashqi ID quyidagicha yoziladi: <code>stars:100</code> yoki <code>premium:3</code>."
        ),
        "parent": "root",
        "items": [
            ("masked", "fragment_seed", "\U0001F511 Hamyon seed iborasi"),
            ("masked", "fragment_ton_api_key", "\U0001F310 TON API kaliti (Toncenter)"),
            ("masked", "fragment_cookies", "\U0001F36A fragment.com cookie'lari"),
            ("edit", "fragment_wallet_version", "\U0001F45B Hamyon versiyasi (V5R1/V4R2)"),
            ("edit", "fragment_api_provider", "\U0001F6F0️ TON API turi (auto/tonapi/toncenter)"),
            ("test_fragment", None, "\U0001F50C Ulanishni tekshirish (pul sarflamaydi)"),
        ],
    },
    "reseller": {
        "title": "\U0001F310 <b>Reseller API</b>",
        "intro": (
            "Tashqi ta'minotchi API'si (API rejimida yetkazilgan mahsulotlar uchun).\n"
            "Bo'sh qoldirilsa, .env fayldagi qiymat ishlatiladi."
        ),
        "parent": "root",
        "items": [
            ("masked", "reseller_api_key", "\U0001F511 API kaliti"),
            ("edit", "reseller_api_base_url", "\U0001F517 API manzili (URL)"),
            ("test_reseller", None, "\U0001F50C Ulanishni tekshirish"),
        ],
    },
    "shamekh": {
        "title": "\U0001F310 <b>Shamekh API</b>",
        "intro": (
            "Ikkinchi, mustaqil ta'minotchi (Reseller API'dan alohida — o'zining manzili va "
            "kaliti bilan). Mahsulotda Provider = <code>shamekh_api</code>, Tashqi ID = "
            "ta'minotchining mahsulot ID'si (masalan <code>1</code>) qilib qo'yiladi.\n"
            "Bo'sh qoldirilsa, .env fayldagi qiymat ishlatiladi."
        ),
        "parent": "root",
        "items": [
            ("masked", "shamekh_api_key", "\U0001F511 API kaliti"),
            ("edit", "shamekh_api_base_url", "\U0001F517 API manzili (URL)"),
            ("test_shamekh", None, "\U0001F50C Ulanishni tekshirish"),
        ],
    },
}


def admin_settings_menu_kb(group: str = "root") -> InlineKeyboardMarkup:
    spec = SETTINGS_GROUPS.get(group) or SETTINGS_GROUPS["root"]
    rows: list[list[InlineKeyboardButton]] = []

    for kind, key, label in spec["items"]:
        if kind == "group":
            cb = AdminSettingsCB(action="group", key=key).pack()
        elif kind == "toggle":
            cb = AdminSettingsCB(action="toggle", key=key, group=group).pack()
        elif kind == "edit":
            cb = AdminSettingsCB(action="edit", key=key, group=group).pack()
        elif kind == "masked":
            cb = AdminSettingsCB(action="edit_masked", key=key, group=group).pack()
        elif kind == "lang":
            cb = AdminSettingsCB(action="pick_lang", key=key, group=group).pack()
        elif kind == "phones":
            cb = AdminPhoneCB(action="list").pack()
        elif kind == "test_fragment":
            cb = AdminSettingsCB(action="test_fragment", group=group).pack()
        elif kind == "test_reseller":
            cb = AdminSettingsCB(action="test_reseller", group=group).pack()
        elif kind == "test_shamekh":
            cb = AdminSettingsCB(action="test_shamekh", group=group).pack()
        elif kind == "referral_shop":
            cb = AdminSettingsCB(action="referral_shop", group=group).pack()
        elif kind == "button_manager":
            cb = AdminButtonCB(action="root").pack()
        else:  # pragma: no cover - guards against a typo'd spec entry
            continue
        rows.append([InlineKeyboardButton(text=label, callback_data=cb)])

    parent = spec.get("parent")
    if parent:
        rows.append(
            [InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminSettingsCB(action="group", key=parent).pack())]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_phone_whitelist_kb(entries: list) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"\U0001F5D1️ +{e.phone_number}" + (f" ({e.note})" if e.note else ""),
                callback_data=AdminPhoneCB(action="remove", phone_id=e.id).pack(),
            )
        ]
        for e in entries
    ]
    rows.append([InlineKeyboardButton(text="➕ Raqam qo'shish", callback_data=AdminPhoneCB(action="add").pack())])
    rows.append(
        [
            InlineKeyboardButton(
                text="\U0001F519 Orqaga",
                callback_data=AdminSettingsCB(action="group", key="access").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_referral_withdraw_kb(withdrawal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ To'landi",
                    callback_data=AdminReferralWithdrawCB(action="paid", withdrawal_id=withdrawal_id).pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish",
                    callback_data=AdminReferralWithdrawCB(action="reject", withdrawal_id=withdrawal_id).pack(),
                ),
            ]
        ]
    )


def admin_referral_rewards_list_kb(rewards: list) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'🟢' if r.is_active else '⚪'} {r.name} — {fmt_price(float(r.cost))}",
                callback_data=AdminReferralRewardCB(action="open", reward_id=r.id).pack(),
            )
        ]
        for r in rewards
    ]
    rows.append(
        [InlineKeyboardButton(text="➕ Yangi sovg'a", callback_data=AdminReferralRewardCB(action="add").pack())]
    )
    # Lives inside Sozlamalar -> Referal dasturi now (not its own main-menu
    # button anymore), so "back" returns there instead of leaving a dead end.
    rows.append(
        [InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminSettingsCB(action="group", key="referral").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_referral_reward_detail_kb(reward) -> InlineKeyboardMarkup:
    rid = reward.id
    visibility_text = "\U0001F648 Yashirish" if reward.is_active else "\U0001F441 Ko'rsatish"

    def cb(action: str, field: str = "") -> str:
        return AdminReferralRewardCB(action=action, reward_id=rid, field=field).pack()

    from app.database.models.enums import ReferralCurrency  # local import avoids a cycle

    currency_text = (
        "\U0001F4B1 Valyuta: \U0001F3AF Ball"
        if reward.currency_type == ReferralCurrency.POINTS
        else "\U0001F4B1 Valyuta: \U0001F4B5 Sotuv valyutasi"
    )

    rows = [
        [
            InlineKeyboardButton(text="✏️ Nomi", callback_data=cb("edit_field", "name")),
            InlineKeyboardButton(text="\U0001F4B0 Narxi", callback_data=cb("edit_field", "cost")),
        ],
        [InlineKeyboardButton(text=currency_text, callback_data=cb("toggle_currency"))],
        [InlineKeyboardButton(text="\U0001F4DD Izoh", callback_data=cb("edit_field", "description"))],
        [
            InlineKeyboardButton(text=visibility_text, callback_data=cb("toggle_active")),
            InlineKeyboardButton(text="\U0001F5D1️ O'chirish", callback_data=cb("delete")),
        ],
        [InlineKeyboardButton(text="\U0001F519 Ro'yxatga qaytish", callback_data=AdminReferralRewardCB(action="list").pack())],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_reward_kb(reward_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=AdminReferralRewardCB(action="confirm_delete", reward_id=reward_id).pack()),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data=AdminReferralRewardCB(action="open", reward_id=reward_id).pack()),
            ]
        ]
    )


def admin_referral_redemption_kb(redemption_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Yetkazildi",
                    callback_data=AdminReferralRedemptionCB(action="fulfilled", redemption_id=redemption_id).pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish",
                    callback_data=AdminReferralRedemptionCB(action="reject", redemption_id=redemption_id).pack(),
                ),
            ]
        ]
    )


def admin_users_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="\U0001F50E Foydalanuvchini qidirish (ID yoki username)", callback_data=AdminUserCB(action="search_prompt").pack())],
            [InlineKeyboardButton(text="\U0001F4E4 To'liq sotuv hisobotini yuklab olish (CSV)", callback_data=AdminUserCB(action="export_sales").pack())],
        ]
    )


def admin_user_search_results_kb(users: list) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{u.full_name or '-'} (@{u.username or '-'}) [{u.telegram_id}]",
                callback_data=AdminUserCB(action="profile", user_id=u.id).pack(),
            )
        ]
        for u in users
    ]
    rows.append(
        [InlineKeyboardButton(text="\U0001F519 Qayta qidirish", callback_data=AdminUserCB(action="search_prompt").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_profile_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ 💵 Sotuv balansi", callback_data=AdminUserCB(action="balance_add", user_id=user_id).pack()),
                InlineKeyboardButton(text="➖ 💵 Sotuv balansi", callback_data=AdminUserCB(action="balance_sub", user_id=user_id).pack()),
            ],
            [
                InlineKeyboardButton(text="➕ 🎯 Ball", callback_data=AdminUserCB(action="points_add", user_id=user_id).pack()),
                InlineKeyboardButton(text="➖ 🎯 Ball", callback_data=AdminUserCB(action="points_sub", user_id=user_id).pack()),
            ],
            [InlineKeyboardButton(text="✉️ Xabar yuborish", callback_data=AdminUserCB(action="message", user_id=user_id).pack())],
            [InlineKeyboardButton(text="\U0001F4E6 Buyurtmalari", callback_data=AdminUserCB(action="orders", user_id=user_id).pack())],
            [InlineKeyboardButton(text="\U0001F519 Qidiruvga qaytish", callback_data=AdminUserCB(action="search_prompt").pack())],
        ]
    )


def settings_language_pick_kb(base_key: str, group: str = "root") -> InlineKeyboardMarkup:
    labels = {"uz": "\U0001F1FA\U0001F1FF UZ", "ru": "\U0001F1F7\U0001F1FA RU", "en": "\U0001F1EC\U0001F1E7 EN"}
    rows = [
        [
            InlineKeyboardButton(
                text=label,
                callback_data=AdminSettingsCB(action="edit", key=f"{base_key}_{code}", group=group).pack(),
            )
            for code, label in labels.items()
        ],
        [
            InlineKeyboardButton(
                text="\U0001F519 Orqaga", callback_data=AdminSettingsCB(action="group", key=group).pack()
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_lang_pick_kb(product_id: int, field_base: str, group: str = "root") -> InlineKeyboardMarkup:
    labels = {"uz": "\U0001F1FA\U0001F1FF UZ", "ru": "\U0001F1F7\U0001F1FA RU", "en": "\U0001F1EC\U0001F1E7 EN"}
    rows = [
        [
            InlineKeyboardButton(
                text=label,
                callback_data=AdminProductCB(
                    action="edit_field", product_id=product_id, field=f"{field_base}_{code}"
                ).pack(),
            )
            for code, label in labels.items()
        ],
        [
            InlineKeyboardButton(
                text="\U0001F519 Orqaga",
                callback_data=AdminProductCB(action="group", product_id=product_id, field=group).pack(),
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_broadcast_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="\U0001F465 Barchaga", callback_data=AdminBroadcastCB(action="all").pack())],
            [InlineKeyboardButton(text="✅ Xarid qilganlarga", callback_data=AdminBroadcastCB(action="bought").pack())],
            [InlineKeyboardButton(text="\U0001F6AB Xarid qilmaganlarga", callback_data=AdminBroadcastCB(action="not_bought").pack())],
            [InlineKeyboardButton(text="\U0001F4E6 Mahsulot bo'yicha", callback_data=AdminBroadcastCB(action="by_product").pack())],
        ]
    )


def admin_broadcast_product_pick_kb(products: list[Product]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{product_button_emoji_prefix(p)}{p.name}",
                icon_custom_emoji_id=getattr(p, "custom_emoji_id", None),
                callback_data=AdminBroadcastCB(action="product_pick", product_id=p.id).pack(),
            )
        ]
        for p in products
    ]
    rows.append(
        [InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminBroadcastCB(action="menu").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_broadcast_product_audience_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Shuni xarid qilganlarga",
                    callback_data=AdminBroadcastCB(action="product_bought", product_id=product_id).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="\U0001F6AB Shuni xarid qilmaganlarga",
                    callback_data=AdminBroadcastCB(action="product_not_bought", product_id=product_id).pack(),
                )
            ],
            [InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminBroadcastCB(action="by_product").pack())],
        ]
    )


def admin_broadcast_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, yuborish", callback_data=AdminBroadcastCB(action="confirm").pack()),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data=AdminBroadcastCB(action="cancel").pack()),
            ]
        ]
    )


# ----------------------------------------------------------------------
# Button Manager — presentation-only editor for app.services.button_registry
# entries. Deliberately reads BUTTON_REGISTRY directly (no separate static
# GROUPS dict here) so the registry stays the single source of truth for
# which buttons exist — this screen only ever lists/edits what's already
# there, it can't create a new button or change what one does.
# ----------------------------------------------------------------------

_BUTTON_GROUP_LABELS = {
    "main_menu": "\U0001F3E0 Asosiy menyu",
    "product": "\U0001F6CD️ Mahsulot / to'lov tugmalari",
}

_BUTTON_STYLE_LABELS = {
    None: "⚪ Standart (avtomatik)",
    "primary": "\U0001F535 Primary (ko'k)",
    "success": "\U0001F7E2 Success (yashil)",
    "danger": "\U0001F534 Danger (qizil)",
}


def admin_button_root_kb() -> InlineKeyboardMarkup:
    from app.services.button_registry import list_groups

    rows = [
        [InlineKeyboardButton(text=_BUTTON_GROUP_LABELS.get(g, g), callback_data=AdminButtonCB(action="group", group=g).pack())]
        for g in list_groups()
    ]
    rows.append([InlineKeyboardButton(text="\U0001F50D Qidirish", callback_data=AdminButtonCB(action="search_prompt").pack())])
    rows.append(
        [InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminSettingsCB(action="group", key="root").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_button_list_kb(group: str, enabled_by_key: dict[str, bool]) -> InlineKeyboardMarkup:
    from app.services.button_registry import list_groups

    defs = list_groups().get(group, [])
    rows = []
    for d in defs:
        mark = "✅" if enabled_by_key.get(d.key, True) else "\U0001F6AB"
        rows.append(
            [InlineKeyboardButton(text=f"{mark} {d.label or d.key}", callback_data=AdminButtonCB(action="open", key=d.key).pack())]
        )
    rows.append([InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminButtonCB(action="root").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_button_detail_kb(key: str, group: str) -> InlineKeyboardMarkup:
    def cb(action: str, **extra) -> str:
        return AdminButtonCB(action=action, key=key, group=group, **extra).pack()

    rows = [
        [InlineKeyboardButton(text="✏️ Matn (til bo'yicha)", callback_data=cb("pick_lang_text"))],
        [InlineKeyboardButton(text="\U0001F3A8 Rang (style)", callback_data=cb("style_menu"))],
        [InlineKeyboardButton(text="\U0001F600 Emoji o'zgartirish", callback_data=cb("emoji_prompt"))],
        [InlineKeyboardButton(text="\U0001F441 Ko'rish (preview)", callback_data=cb("preview"))],
        [InlineKeyboardButton(text="\U0001F504 Yoqish/O'chirish", callback_data=cb("toggle_enabled"))],
        [InlineKeyboardButton(text="♻️ Standartga qaytarish", callback_data=cb("reset"))],
        [InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminButtonCB(action="group", group=group).pack())],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_button_style_pick_kb(key: str, group: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=AdminButtonCB(action="set_style", key=key, group=group, style=style or "_default").pack())]
        for style, label in _BUTTON_STYLE_LABELS.items()
    ]
    rows.append([InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminButtonCB(action="open", key=key, group=group).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_button_lang_pick_kb(key: str, group: str) -> InlineKeyboardMarkup:
    labels = {"uz": "\U0001F1FA\U0001F1FF UZ", "ru": "\U0001F1F7\U0001F1FA RU", "en": "\U0001F1EC\U0001F1E7 EN"}
    rows = [
        [
            InlineKeyboardButton(text=label, callback_data=AdminButtonCB(action="edit_text", key=key, group=group, lang=code).pack())
            for code, label in labels.items()
        ],
        [InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminButtonCB(action="open", key=key, group=group).pack())],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_button_search_results_kb(keys: list[str]) -> InlineKeyboardMarkup:
    from app.services.button_registry import get_button_def

    rows = []
    for key in keys:
        d = get_button_def(key)
        rows.append([InlineKeyboardButton(text=(d.label if d else key), callback_data=AdminButtonCB(action="open", key=key).pack())])
    rows.append([InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminButtonCB(action="root").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_kb(context: str, target_id: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha", callback_data=ConfirmCB(action="yes", context=context, target_id=target_id).pack()),
                InlineKeyboardButton(text="❌ Yo'q", callback_data=ConfirmCB(action="no", context=context, target_id=target_id).pack()),
            ]
        ]
    )
