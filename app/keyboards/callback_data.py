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
    # True only from the shop list / "buy again" — a genuinely fresh look at
    # the product, as opposed to the in-flow "back" buttons on the qty
    # picker and payment screen (which reopen the SAME product mid-purchase
    # and must not wipe the recipient/amount just entered). See
    # open_product() in handlers/user/shop.py.
    fresh: bool = False


class OrderCB(CallbackData, prefix="order"):
    action: str  # approve | reject | ask_reject_reason | write_manual | retry_auto
    order_id: int
    # Where the admin came from, so "back" returns to that exact list page
    # instead of dumping them at the top. `str | None`, never plain `str`:
    # aiogram unpacks an absent field as None and a non-Optional str would
    # make the whole button silently match no handler.
    src: str | None = None
    page: int = 0


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


class RecipientCB(CallbackData, prefix="rcpt"):
    action: str  # myself | other | change
    product_id: int = 0


class CardAutoCB(CallbackData, prefix="cauto"):
    action: str  # buy | paid | cancel | manual | admin_confirm | admin_reject
    product_id: int = 0
    order_id: int = 0
    qty: int = 1


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
    action: str  # menu | pending | approved | delivered | failed | rejected |
    #              search | retry_all | open
    page: int = 0
    order_id: int = 0


class AdminSettingsCB(CallbackData, prefix="aset"):
    action: str  # edit | edit_masked | toggle | pick_lang | test_reseller | test_fragment | group
    key: str | None = None
    # Which settings group the button lives in, so after a toggle (or a
    # "back" from the language picker) we can re-render that same submenu
    # instead of dumping the admin at the top level. `str | None` — never
    # plain `str` — because aiogram unpacks an absent/empty CallbackData
    # field as None, which fails validation on a non-Optional str field
    # and makes the button silently match no handler at all.
    group: str | None = None


class AdminAdminsCB(CallbackData, prefix="aadm"):
    action: str  # list | add | remove
    telegram_id: int = 0


class AdminBroadcastCB(CallbackData, prefix="abcast"):
    action: str  # menu | all | bought | not_bought | by_product | product_pick | product_bought | product_not_bought | confirm | cancel
    product_id: int = 0


class ReferralCB(CallbackData, prefix="ref"):
    action: str  # withdraw | rules | profile_back | confirm


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
    action: str  # list | open | add | edit_field | toggle_active | toggle_currency | delete | confirm_delete | back
    reward_id: int = 0
    field: str | None = None


class AdminReferralRedemptionCB(CallbackData, prefix="arefrd"):
    action: str  # fulfilled | reject
    redemption_id: int = 0


class AdminUserCB(CallbackData, prefix="auser"):
    action: str  # search_prompt | export_sales | profile | balance_add | balance_sub |
    #              points_add | points_sub | message | orders
    user_id: int = 0


class OnboardingCB(CallbackData, prefix="ogate"):
    action: str  # accept_offer | check_channel


class CaptchaCB(CallbackData, prefix="capt"):
    action: str  # answer
    # Each option button carries whether *it* is the correct one — this is
    # a low-stakes human-friction check, not a security boundary, so there's
    # no need for server-side FSM state just to remember the right answer
    # between showing the question and checking the tap.
    correct: bool = False


class AdminPhoneCB(CallbackData, prefix="aphone"):
    action: str  # list | add | remove
    phone_id: int = 0


class ConfirmCB(CallbackData, prefix="confirm"):
    action: str  # yes | no
    context: str | None = None
    target_id: int = 0
