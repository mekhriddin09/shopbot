from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.database.models import Product
from app.database.models.enums import DeliveryMode
from app.keyboards.callback_data import (
    AdminBroadcastCB,
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
from app.utils.formatting import fmt_price

ADMIN_BTN_PRODUCTS = "\U0001F6CD️ Mahsulotlar"
ADMIN_BTN_ORDERS = "\U0001F4E5 Buyurtmalar"
ADMIN_BTN_STATS = "\U0001F4CA Statistika"
ADMIN_BTN_SETTINGS = "⚙️ Sozlamalar"
ADMIN_BTN_BROADCAST = "\U0001F4E2 Xabar yuborish"
ADMIN_BTN_REFERRAL_REWARDS = "\U0001F381 Referral do'koni"
ADMIN_BTN_USERS = "\U0001F464 Foydalanuvchilar"
ADMIN_BTN_EXIT = "\U0001F6AA Admin paneldan chiqish"


def admin_main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ADMIN_BTN_PRODUCTS), KeyboardButton(text=ADMIN_BTN_ORDERS)],
            [KeyboardButton(text=ADMIN_BTN_STATS), KeyboardButton(text=ADMIN_BTN_SETTINGS)],
            [KeyboardButton(text=ADMIN_BTN_BROADCAST), KeyboardButton(text=ADMIN_BTN_REFERRAL_REWARDS)],
            [KeyboardButton(text=ADMIN_BTN_USERS)],
            [KeyboardButton(text=ADMIN_BTN_EXIT)],
        ],
        resize_keyboard=True,
    )


def admin_products_list_kb(products: list[Product]) -> InlineKeyboardMarkup:
    rows = []
    for p in products:
        mark = "\U0001F7E2" if p.is_visible else "⚪"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {p.emoji} {p.name}",
                    callback_data=AdminProductCB(action="open", product_id=p.id).pack(),
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="➕ Yangi mahsulot", callback_data=AdminProductCB(action="add").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_product_detail_kb(product: Product) -> InlineKeyboardMarkup:
    pid = product.id
    visibility_text = "\U0001F648 Yashirish" if product.is_visible else "\U0001F441 Ko'rsatish"

    def cb(action: str, field: str = "") -> str:
        return AdminProductCB(action=action, product_id=pid, field=field).pack()

    rows = [
        [
            InlineKeyboardButton(text="✏️ Nomi", callback_data=cb("edit_field", "name")),
            InlineKeyboardButton(text="\U0001F3F7️ Emoji", callback_data=cb("edit_field", "emoji")),
        ],
        [
            InlineKeyboardButton(text="\U0001F4DD Tavsif", callback_data=cb("edit_field", "description")),
            InlineKeyboardButton(text="\U0001F4B0 Narx (UZS)", callback_data=cb("edit_field", "price")),
        ],
        [
            InlineKeyboardButton(text="\U0001F310 Nomi (til bo'yicha)", callback_data=cb("pick_lang_field", "name")),
            InlineKeyboardButton(text="\U0001F310 Tavsif (til bo'yicha)", callback_data=cb("pick_lang_field", "description")),
        ],
        [
            InlineKeyboardButton(text="\U0001FA99 Narx (USD/kripto)", callback_data=cb("edit_field", "price_usd")),
            InlineKeyboardButton(text="⭐ Narx (Stars)", callback_data=cb("edit_field", "price_stars")),
        ],
        [
            InlineKeyboardButton(text="\U0001F5BC️ Rasm", callback_data=cb("edit_field", "image")),
            InlineKeyboardButton(text="\U0001F4B3 To'lov ma'lumoti", callback_data=cb("edit_field", "payment_instructions")),
        ],
        [
            InlineKeyboardButton(text="\U0001F4E6 Yetkazish rejimi", callback_data=cb("set_mode")),
            InlineKeyboardButton(text="\U0001F522 Tartib raqami", callback_data=cb("edit_field", "sort_order")),
        ],
        *(
            [
                [
                    InlineKeyboardButton(text="\U0001F511 Provider", callback_data=cb("edit_field", "provider_key")),
                    InlineKeyboardButton(text="\U0001F194 Tashqi ID", callback_data=cb("edit_field", "external_product_id")),
                ]
            ]
            if product.delivery_mode == DeliveryMode.API
            else []
        ),
        [
            InlineKeyboardButton(
                text="\U0001F310 Yetkazishdan keyingi xabar (til bo'yicha)",
                callback_data=cb("pick_lang_field", "delivery_instructions"),
            ),
        ],
        [
            InlineKeyboardButton(text="\U0001F4E6 Inventar", callback_data=AdminInventoryCB(action="menu", product_id=pid).pack()),
        ],
        [
            InlineKeyboardButton(
                text=("\U0001F91D Referral: yoqilgan ✅" if product.referral_eligible else "\U0001F91D Referral: o'chirilgan"),
                callback_data=cb("toggle_referral"),
            ),
        ],
        [
            InlineKeyboardButton(
                text=("⚡️ Avto karta: yoqilgan ✅" if product.card_auto_enabled else "⚡️ Avto karta: o'chirilgan"),
                callback_data=cb("toggle_card_auto"),
            ),
        ],
        [
            InlineKeyboardButton(
                text=("\U0001F512 Qo'lda tasdiqlash ✅" if product.card_manual_confirm else "\U0001F513 Avtomatik yetkazish"),
                callback_data=cb("toggle_card_manual"),
            ),
        ],
        [
            InlineKeyboardButton(text="\U0001F522 Min. buyurtma soni", callback_data=cb("edit_field", "min_order_qty")),
            InlineKeyboardButton(text="\U0001F522 Max. buyurtma soni", callback_data=cb("edit_field", "max_order_qty")),
        ],
        [
            InlineKeyboardButton(text=visibility_text, callback_data=cb("toggle_visibility")),
            InlineKeyboardButton(text="\U0001F5D1️ O'chirish", callback_data=cb("delete")),
        ],
        [InlineKeyboardButton(text="\U0001F519 Ro'yxatga qaytish", callback_data=AdminProductCB(action="list").pack())],
    ]
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


def admin_order_detail_kb(order) -> InlineKeyboardMarkup:
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
                InlineKeyboardButton(text="✅ Tasdiqlash va yetkazish", callback_data=OrderCB(action="approve", order_id=oid).pack()),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=OrderCB(action="reject", order_id=oid).pack()),
            ]
        )
    if order.status in (OrderStatus.APPROVED, OrderStatus.FAILED):
        rows.append(
            [InlineKeyboardButton(text="✍️ Qo'lda yuborish", callback_data=OrderCB(action="write_manual", order_id=oid).pack())]
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


def admin_write_manual_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
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
            ("group", "access", "\U0001F512 Kirish nazorati"),
            ("group", "reseller", "\U0001F310 Reseller API"),
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
            "Ikkita mustaqil mukofot turi bor — pastdagi ikki bo'limda alohida sozlanadi:\n\n"
            "\U0001F4B5 <b>Sotuv mukofoti</b> — taklif qilingan odam <b>xarid qilganda</b> beriladi. "
            "Pul sifatida yechib olish mumkin.\n"
            "\U0001F3AF <b>Ball</b> — taklif qilingan odam <b>tasdiqdan o'tganda</b> beriladi. "
            "Faqat referal do'konida sarflanadi, pul sifatida yechilmaydi."
        ),
        "parent": "root",
        "items": [
            ("toggle", "referral_enabled", "\U0001F91D Referal tizimi (umumiy)"),
            ("group", "referral_sales", "\U0001F4B5 Sotuv mukofoti (xarid uchun)"),
            ("group", "referral_points", "\U0001F3AF Ball (taklif uchun)"),
            ("lang", "referral_rules", "\U0001F4DC Referal qoidalari matni"),
        ],
    },
    "referral_sales": {
        "title": "\U0001F4B5 <b>Sotuv mukofoti</b>",
        "intro": (
            "Taklif qilingan odam xarid qilganda taklif qilgan odamga beriladi.\n"
            "Miqdorni qat'iy summa (<code>5000</code>) yoki foiz (<code>5%</code>) sifatida yozish mumkin.\n"
            "Eslatma: mukofot faqat mahsulot sahifasida \"Referral: yoqilgan\" bo'lsa beriladi."
        ),
        "parent": "referral",
        "items": [
            ("toggle", "referral_first_order_enabled", "\U0001F381 1-buyurtma mukofoti"),
            ("edit", "referral_first_order_value", "✏️ 1-buyurtma miqdori"),
            ("toggle", "referral_recurring_enabled", "\U0001F501 Doimiy mukofot"),
            ("edit", "referral_recurring_value", "✏️ Doimiy mukofot miqdori"),
            ("edit", "referral_currency", "\U0001F4B1 Valyuta nomi"),
            ("edit", "referral_withdraw_min", "\U0001F4B0 Min. pul yechish miqdori"),
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
            ("phones", None, "☎️ Ruxsat etilgan chet el raqamlari"),
        ],
    },
    "access": {
        "title": "\U0001F512 <b>Kirish nazorati</b>",
        "intro": (
            "Yoqilsa, foydalanuvchi botdan foydalanishdan oldin oferta matniga rozilik beradi "
            "va majburiy kanalga obuna bo'ladi. Adminlar bu tekshiruvdan ozod.\n"
            "⚠️ Oferta matni bo'sh bo'lsa, tizim xavfsizlik uchun hech kimni bloklamaydi.\n"
            "⚠️ Bot majburiy kanalda administrator bo'lishi shart."
        ),
        "parent": "root",
        "items": [
            ("toggle", "onboarding_gate_enabled", "\U0001F6AA Majburiy oferta + kanal"),
            ("lang", "oferta_text", "\U0001F4C4 Oferta matni"),
            ("edit", "required_channel", "\U0001F4E2 Majburiy kanal (@username/ID)"),
            ("edit", "required_channel_url", "\U0001F517 Kanal havolasi (join link)"),
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
        elif kind == "test_reseller":
            cb = AdminSettingsCB(action="test_reseller", group=group).pack()
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
                callback_data=AdminSettingsCB(action="group", key="referral_points").pack(),
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


def product_lang_pick_kb(product_id: int, field_base: str) -> InlineKeyboardMarkup:
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
                text="\U0001F519 Orqaga", callback_data=AdminProductCB(action="open", product_id=product_id).pack()
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
                text=f"{p.emoji} {p.name}",
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


def confirm_kb(context: str, target_id: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha", callback_data=ConfirmCB(action="yes", context=context, target_id=target_id).pack()),
                InlineKeyboardButton(text="❌ Yo'q", callback_data=ConfirmCB(action="no", context=context, target_id=target_id).pack()),
            ]
        ]
    )
