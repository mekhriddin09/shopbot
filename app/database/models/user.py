from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="uz", server_default="uz")
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # Referral program: who invited this user (set once, on first /start with
    # a `ref<id>` deep-link payload) and their accumulated, not-yet-withdrawn
    # referral earnings (unit is whatever the "referral_currency" setting
    # says — UZS/USD/USDT/points, it's just a number here).
    referred_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    referral_balance: Mapped[float] = mapped_column(Numeric(12, 2), default=0, server_default="0")

    # Second, independent referral currency ("Ball" by default, renameable
    # via the "referral_points_name" setting): earned by inviting users who
    # pass the phone+captcha confirmation, spendable ONLY in the referral
    # shop — never withdrawable as cash. See ReferralCurrency in enums.py
    # for why the two are kept separate.
    referral_points: Mapped[float] = mapped_column(Numeric(12, 2), default=0, server_default="0")

    # Onboarding gate: mandatory oferta (terms) acceptance + mandatory
    # channel subscription, both admin-configurable/toggle-able (see
    # Setting "onboarding_gate_enabled"), checked by OnboardingGateMiddleware
    # before any other handler runs.
    oferta_accepted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # Referral-confirmation anti-fraud gate: only applies to users who
    # arrived via a referral link (`referred_by_id` set). Must share a real
    # phone number (UZ or admin-whitelisted) and pass a simple math captcha
    # before they count toward their referrer's stats/rewards — see
    # ReferralRepository.get_stats and ReferralService.credit_for_delivered_order.
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    referral_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Confirmation is offered once, unprompted, on entry — then never
    # auto-shown again (the user can always come back to it from the
    # Referral section). Without this flag the prompt would reappear on
    # every single message for anyone who declined or failed it.
    referral_prompt_shown: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Guards the invite reward against ever being paid twice for the same
    # referred user (e.g. if confirmation were somehow re-run).
    referral_confirm_rewarded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    reviews: Mapped[list["Review"]] = relationship(back_populates="user")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} tg={self.telegram_id}>"
