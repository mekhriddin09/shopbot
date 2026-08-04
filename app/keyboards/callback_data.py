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
    qty: int = 1
    preorder: bool = False


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
    qty: int = 1
    preorder: bool = False


class StarsCB(CallbackData, prefix="stars"):
    action: str  # buy | cancel
    product_id: int = 0
    order_id: int = 0
    qty: int = 1
    preorder: bool = False


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
    action: str  # edit | edit_masked | toggle | pick_lang | test_reseller
    key: str | None = None


class AdminAdminsCB(CallbackData, prefix="aadm"):
    action: str  # list | add | remove
    telegram_id: int = 0


class AdminBroadcastCB(CallbackData, prefix="abcast"):
    action: str  # menu | all | bought | not_bought | by_product | product_pick | product_bought | product_not_bought | confirm | cancel
    product_id: int = 0


class ReferralCB(CallbackData, prefix="ref"):
    action: str  # withdraw | rules | profile_back


class QtyCB(CallbackData, prefix="qty"):
    action: str  # show | inc | dec | set | confirm
    product_id: int
    qty: int = 1
    flow: str = "card"  # card | crypto | stars
    # THE BUG: aiogram's CallbackData encodes an empty string field as an
    # absent value, and unpacks that back to `None` — not back to `""`.
    # This field used to be declared as plain `str = ""`, so any button
    # packed with an empty provider (i.e. every "card" and "stars" flow
    # button, since only "crypto" ever sets a real provider) produced a
    # callback_data string that FAILED to unpack (pydantic rejected `None`
    # for a `str` field). aiogram treats an unpack failure as "this filter
    # doesn't match" rather than raising, so those buttons silently matched
    # no handler at all — the client shows an endless "loading" spinner on
    # tap instead of any error. `str | None` fixes the round-trip; every
    # call site already does `callback_data.provider or ""` so `None` flows
    # through safely.
    provider: str | None = None


class StockNotifyCB(CallbackData, prefix="stockw"):
    action: str  # subscribe
    product_id: int


class AdminStockWaitersCB(CallbackData, prefix="astockw"):
    action: str  # list | notify_all
    product_id: int = 0


class AdminReferralWithdrawCB(CallbackData, prefix="arefw"):
    action: str  # paid | reject
    withdrawal_id: int = 0


class ReferralRewardCB(CallbackData, prefix="refrw"):
    action: str  # list | open | buy | skip_note | back
    reward_id: int = 0


class AdminReferralRewardCB(CallbackData, prefix="arefrw"):
    action: str  # list | open | add | edit_field | toggle_active | delete | confirm_delete | back
    reward_id: int = 0
    field: str | None = None


class AdminReferralRedemptionCB(CallbackData, prefix="arefrd"):
    action: str  # fulfilled | reject
    redemption_id: int = 0


class AdminUserCB(CallbackData, prefix="auser"):
    action: str  # search_prompt | export_sales | profile | balance_add | balance_sub | message | orders
    user_id: int = 0


class ConfirmCB(CallbackData, prefix="confirm"):
    action: str  # yes | no
    context: str | None = None
    target_id: int = 0
