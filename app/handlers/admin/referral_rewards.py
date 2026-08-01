"""Admin side of the referral "shop": managing the catalog of redeemable
rewards (mirrors app/handlers/admin/products.py) and deciding pending
redemption requests (mirrors the withdrawal paid/reject handlers in
settings.py)."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters.is_admin import IsAdmin
from app.keyboards.admin_kb import (
    ADMIN_BTN_REFERRAL_REWARDS,
    admin_referral_reward_detail_kb,
    admin_referral_rewards_list_kb,
    confirm_delete_reward_kb,
)
from app.keyboards.callback_data import AdminReferralRedemptionCB, AdminReferralRewardCB
from app.repositories.referral_repo import ReferralRepository
from app.states.admin_states import AdminInput
from app.utils.formatting import fmt_price
from app.utils.i18n import t

router = Router(name="admin_referral_rewards")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

admin_actions_logger = logging.getLogger("admin_actions")

FIELD_PROMPTS = {
    "name": "Sovg'a nomini yozing (masalan: 100 ta Telegram Stars):",
    "cost": "Narxini (referral balansidan yechiladigan ball/summa) raqamda yozing (masalan: 20000):",
    "description": "Qo'shimcha izoh yozing (mijozga ko'rinadi, ixtiyoriy — bo'sh qoldirish uchun '-' yuboring):",
}


def _reward_summary(reward) -> str:
    visibility = "\U0001F7E2 Ko'rinadi" if reward.is_active else "⚪ Yashirilgan"
    description_line = f"\n{reward.description}" if reward.description else ""
    return (
        f"\U0001F381 <b>{reward.name}</b>{description_line}\n\n"
        f"\U0001F4B0 Narxi: {fmt_price(float(reward.cost))}\n"
        f"{visibility}"
    )


@router.message(F.text == ADMIN_BTN_REFERRAL_REWARDS)
async def referral_rewards_menu(message: Message, session: AsyncSession) -> None:
    rewards = await ReferralRepository(session).list_all_rewards()
    await message.answer(
        "\U0001F381 Referral do'koni — mijozlar o'z referral balansini shu sovg'alarga almashtirishlari mumkin:",
        reply_markup=admin_referral_rewards_list_kb(rewards),
    )


@router.callback_query(AdminReferralRewardCB.filter(F.action == "list"))
async def referral_rewards_list_cb(callback: CallbackQuery, session: AsyncSession) -> None:
    rewards = await ReferralRepository(session).list_all_rewards()
    await callback.message.edit_text(
        "\U0001F381 Referral do'koni — mijozlar o'z referral balansini shu sovg'alarga almashtirishlari mumkin:",
        reply_markup=admin_referral_rewards_list_kb(rewards),
    )
    await callback.answer()


@router.callback_query(AdminReferralRewardCB.filter(F.action == "open"))
async def referral_reward_open(callback: CallbackQuery, callback_data: AdminReferralRewardCB, session: AsyncSession) -> None:
    reward = await ReferralRepository(session).get_reward(callback_data.reward_id)
    if reward is None:
        await callback.answer("Sovg'a topilmadi", show_alert=True)
        return
    await callback.message.edit_text(_reward_summary(reward), reply_markup=admin_referral_reward_detail_kb(reward))
    await callback.answer()


@router.callback_query(AdminReferralRewardCB.filter(F.action == "add"))
async def referral_reward_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(action="new_reward_name")
    await callback.message.answer(FIELD_PROMPTS["name"])
    await callback.answer()


@router.callback_query(AdminReferralRewardCB.filter(F.action == "edit_field"))
async def referral_reward_edit_field(callback: CallbackQuery, callback_data: AdminReferralRewardCB, state: FSMContext) -> None:
    field = callback_data.field
    prompt = FIELD_PROMPTS.get(field, "Yangi qiymatni yozing:")
    await state.set_state(AdminInput.waiting_text)
    await state.update_data(action="edit_reward_field", reward_id=callback_data.reward_id, field=field)
    await callback.message.answer(prompt)
    await callback.answer()


@router.callback_query(AdminReferralRewardCB.filter(F.action == "toggle_active"))
async def referral_reward_toggle_active(callback: CallbackQuery, callback_data: AdminReferralRewardCB, session: AsyncSession) -> None:
    referrals = ReferralRepository(session)
    reward = await referrals.get_reward(callback_data.reward_id)
    if reward is None:
        await callback.answer("Sovg'a topilmadi", show_alert=True)
        return
    await referrals.update_reward(reward, is_active=not reward.is_active)
    await callback.message.edit_text(_reward_summary(reward), reply_markup=admin_referral_reward_detail_kb(reward))
    await callback.answer()


@router.callback_query(AdminReferralRewardCB.filter(F.action == "delete"))
async def referral_reward_delete_confirm(callback: CallbackQuery, callback_data: AdminReferralRewardCB) -> None:
    await callback.message.edit_reply_markup(reply_markup=confirm_delete_reward_kb(callback_data.reward_id))
    await callback.answer()


@router.callback_query(AdminReferralRewardCB.filter(F.action == "confirm_delete"))
async def referral_reward_delete(callback: CallbackQuery, callback_data: AdminReferralRewardCB, session: AsyncSession) -> None:
    referrals = ReferralRepository(session)
    reward = await referrals.get_reward(callback_data.reward_id)
    if reward is None:
        await callback.answer("Sovg'a topilmadi", show_alert=True)
        return
    deleted = await referrals.delete_reward(reward)
    all_rewards = await referrals.list_all_rewards()
    if deleted:
        admin_actions_logger.info(
            "referral_reward_deleted id=%s name=%s admin=%s", reward.id, reward.name, callback.from_user.id
        )
        await callback.message.edit_text("✅ Sovg'a o'chirildi.", reply_markup=admin_referral_rewards_list_kb(all_rewards))
        await callback.answer()
        return

    # Already redeemed by someone at least once — hide instead of deleting,
    # same reasoning as product deletion (protects redemption history).
    await referrals.update_reward(reward, is_active=False)
    admin_actions_logger.info(
        "referral_reward_hidden_instead_of_deleted id=%s name=%s admin=%s", reward.id, reward.name, callback.from_user.id
    )
    await callback.message.edit_text(
        "⚠️ Bu sovg'a bo'yicha oldin so'rovlar bo'lgani uchun butunlay o'chirib bo'lmadi "
        "(tarix buzilmasligi uchun himoyalangan).\n\n"
        "\U0001F648 Shuning uchun uni <b>yashirdik</b> — endi referral do'konida mijozlarga ko'rinmaydi.",
        reply_markup=admin_referral_rewards_list_kb(all_rewards),
    )
    await callback.answer()


@router.callback_query(AdminReferralRedemptionCB.filter(F.action == "fulfilled"))
async def referral_redemption_fulfilled(
    callback: CallbackQuery, callback_data: AdminReferralRedemptionCB, session: AsyncSession
) -> None:
    referrals = ReferralRepository(session)
    redemption = await referrals.get_redemption(callback_data.redemption_id)
    if redemption is None:
        await callback.answer("So'rov topilmadi.", show_alert=True)
        return
    await referrals.mark_redemption_fulfilled(redemption, callback.from_user.id)
    await callback.message.edit_text(callback.message.text + "\n\n✅ YETKAZILDI")
    await callback.message.edit_reply_markup(reply_markup=None)
    try:
        await callback.bot.send_message(
            redemption.user.telegram_id,
            t(redemption.user.language, "msg_referral_reward_fulfilled", name=redemption.reward_name_snapshot),
        )
    except Exception:  # noqa: BLE001 - user may have blocked the bot
        pass
    await callback.answer("Yetkazildi deb belgilandi ✅")


@router.callback_query(AdminReferralRedemptionCB.filter(F.action == "reject"))
async def referral_redemption_reject(
    callback: CallbackQuery, callback_data: AdminReferralRedemptionCB, session: AsyncSession
) -> None:
    referrals = ReferralRepository(session)
    redemption = await referrals.get_redemption(callback_data.redemption_id)
    if redemption is None:
        await callback.answer("So'rov topilmadi.", show_alert=True)
        return
    await referrals.mark_redemption_rejected(redemption, callback.from_user.id)
    await callback.message.edit_text(callback.message.text + "\n\n❌ RAD ETILDI (balans qaytarildi)")
    await callback.message.edit_reply_markup(reply_markup=None)
    try:
        await callback.bot.send_message(
            redemption.user.telegram_id,
            t(
                redemption.user.language,
                "msg_referral_reward_rejected",
                name=redemption.reward_name_snapshot,
                amount=fmt_price(float(redemption.cost_snapshot)),
            ),
        )
    except Exception:  # noqa: BLE001 - user may have blocked the bot
        pass
    await callback.answer("Rad etildi")


__all__ = ["router"]
