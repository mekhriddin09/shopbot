"""Typed callback_data factories (aiogram 3).

Using CallbackData factories (instead of hand-built strings) gives us free
parsing/validation on every incoming callback, which closes off a whole
class of "malformed callback" attacks / crashes.
"""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class ShopCB(CallbackData, prefix="shop"):
    action: str  # open | buy | paid | back_to_list | back_to_product
    product_id: int = 0


class OrderCB(CallbackData, prefix="order"):
    action: str  # approve | reject | ask_reject_reason
    order_id: int


class MyOrderCB(CallbackData, prefix="myorder"):
    action: str  # view
    order_id: int


class MyOrdersPageCB(CallbackData, prefix="myordpg"):
    action: str  # page
    page: int = 0


class ReviewCB(CallbackData, prefix="review"):
    action: str  # rate | write | skip
    rating: int = 0


class LangCB(CallbackData, prefix="lang"):
    code: str


class CryptoCB(CallbackData, prefix="crypto"):
    action: str  # buy | check | cancel
    product_id: int = 0
    order_id: int = 0
    provider: str | None = None


class AdminMenuCB(CallbackData, prefix="amenu"):
    action: str  # products | inventory | orders | stats | settings | admins


class AdminProductCB(CallbackData, prefix="aprod"):
    action: str  # list | open | add | edit_field | toggle_visibility | delete | confirm_delete | move_up | move_down | set_mode | set_provider | back
    product_id: int = 0
    field: str | None = None


class AdminInventoryCB(CallbackData, prefix="ainv"):
    action: str  # menu | add_one | bulk | export | view | pick_delete | toggle_select |
    #              delete_selected | confirm_selected | delete_all | confirm_all
    product_id: int = 0
    code_id: int = 0


class AdminOrderListCB(CallbackData, prefix="aordl"):
    action: str  # pending | approved | delivered | failed | rejected


class AdminSettingsCB(CallbackData, prefix="aset"):
    action: str  # edit | toggle
    key: str | None = None


class AdminAdminsCB(CallbackData, prefix="aadm"):
    action: str  # list | add | remove
    telegram_id: int = 0


class AdminBroadcastCB(CallbackData, prefix="abcast"):
    action: str  # menu | all | bought | not_bought | by_product | product_pick | product_bought | product_not_bought | confirm | cancel
    product_id: int = 0


class ConfirmCB(CallbackData, prefix="confirm"):
    action: str  # yes | no
    context: str | None = None
    target_id: int = 0
