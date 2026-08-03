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
    AdminMenuCB,
    AdminOrderListCB,
    AdminProductCB,
    AdminReferralRedemptionCB,
    AdminReferralRewardCB,
    AdminReferralWithdrawCB,
    AdminSettingsCB,
    AdminStockWaitersCB,
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
ADMIN_BTN_EXIT = "\U0001F6AA Admin paneldan chiqish"


def admin_main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ADMIN_BTN_PRODUCTS), KeyboardButton(text=ADMIN_BTN_ORDERS)],
            [KeyboardButton(text=ADMIN_BTN_STATS), KeyboardButton(text=ADMIN_BTN_SETTINGS)],
            [KeyboardButton(text=ADMIN_BTN_BROADCAST), KeyboardButton(text=ADMIN_BTN_REFERRAL_REWARDS)],
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
    ]
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


def admin_write_manual_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Xabar yozish", callback_data=OrderCB(action="write_manual", order_id=order_id).pack())]
        ]
    )


def admin_settings_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="\U0001F44B Xush kelibsiz xabari", callback_data=AdminSettingsCB(action="pick_lang", key="welcome_message").pack())],
        [InlineKeyboardButton(text="\U0001F4AC Yordam xabari", callback_data=AdminSettingsCB(action="pick_lang", key="support_message").pack())],
        [InlineKeyboardButton(text="\U0001F4B3 Umumiy to'lov ma'lumoti", callback_data=AdminSettingsCB(action="pick_lang", key="payment_instructions").pack())],
        [InlineKeyboardButton(text="⭐ Sharhlar matni", callback_data=AdminSettingsCB(action="pick_lang", key="reviews_text").pack())],
        [InlineKeyboardButton(text="\U0001F504 Avto-yetkazish (inventar)", callback_data=AdminSettingsCB(action="toggle", key="automatic_delivery_enabled").pack())],
        [InlineKeyboardButton(text="✍️ Qo'lda yetkazish", callback_data=AdminSettingsCB(action="toggle", key="manual_delivery_enabled").pack())],
        [InlineKeyboardButton(text="\U0001F310 API orqali yetkazish", callback_data=AdminSettingsCB(action="toggle", key="api_delivery_enabled").pack())],
        [InlineKeyboardButton(text="📢 Isbotlar kanali havolasi", callback_data=AdminSettingsCB(action="edit", key="proof_channel_url").pack())],
        [InlineKeyboardButton(text="\U0001FA99 Kripto to'lov (yoq/o'chir)", callback_data=AdminSettingsCB(action="toggle", key="crypto_payment_enabled").pack())],
        [InlineKeyboardButton(text="⭐ Telegram Stars to'lov (yoq/o'chir)", callback_data=AdminSettingsCB(action="toggle", key="stars_payment_enabled").pack())],
        [InlineKeyboardButton(text="\U0001F91D Referral (yoq/o'chir)", callback_data=AdminSettingsCB(action="toggle", key="referral_enabled").pack())],
        [InlineKeyboardButton(text="\U0001F381 1-buyurtma mukofoti (yoq/o'chir)", callback_data=AdminSettingsCB(action="toggle", key="referral_first_order_enabled").pack())],
        [InlineKeyboardButton(text="✏️ 1-buyurtma mukofoti miqdori", callback_data=AdminSettingsCB(action="edit", key="referral_first_order_value").pack())],
        [InlineKeyboardButton(text="\U0001F501 Doimiy mukofot (yoq/o'chir)", callback_data=AdminSettingsCB(action="toggle", key="referral_recurring_enabled").pack())],
        [InlineKeyboardButton(text="✏️ Doimiy mukofot miqdori", callback_data=AdminSettingsCB(action="edit", key="referral_recurring_value").pack())],
        [InlineKeyboardButton(text="✏️ Referral valyutasi (UZS/USD/USDT/Ball)", callback_data=AdminSettingsCB(action="edit", key="referral_currency").pack())],
        [InlineKeyboardButton(text="✏️ Min. pul yechish miqdori", callback_data=AdminSettingsCB(action="edit", key="referral_withdraw_min").pack())],
        [InlineKeyboardButton(text="\U0001F4E6 Oldindan buyurtma (yoq/o'chir)", callback_data=AdminSettingsCB(action="toggle", key="preorder_enabled").pack())],
        [InlineKeyboardButton(text="\U0001F4DC Referral qoidalari (til bo'yicha)", callback_data=AdminSettingsCB(action="pick_lang", key="referral_rules").pack())],
    ]
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

    rows = [
        [
            InlineKeyboardButton(text="✏️ Nomi", callback_data=cb("edit_field", "name")),
            InlineKeyboardButton(text="\U0001F4B0 Narxi (ball)", callback_data=cb("edit_field", "cost")),
        ],
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


def settings_language_pick_kb(base_key: str) -> InlineKeyboardMarkup:
    labels = {"uz": "\U0001F1FA\U0001F1FF UZ", "ru": "\U0001F1F7\U0001F1FA RU", "en": "\U0001F1EC\U0001F1E7 EN"}
    rows = [
        [
            InlineKeyboardButton(
                text=label, callback_data=AdminSettingsCB(action="edit", key=f"{base_key}_{code}").pack()
            )
            for code, label in labels.items()
        ],
        [InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data=AdminMenuCB(action="settings").pack())],
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
