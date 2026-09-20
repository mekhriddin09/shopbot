from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class ButtonConfig(TimestampMixin, Base):
    """Admin-editable *presentation* for one logical button.

    `key` matches a key in `app.services.button_registry.BUTTON_REGISTRY`
    (the code-side source of truth for what a button *does* — its
    `ButtonType`/semantic style default and code-default emoji). This table
    never stores anything about what a button does (no callback, no action,
    no product/order id) — only how it looks. That split is deliberate: the
    Button Manager admin screens are only ever allowed to write to this
    table (and `ButtonTranslation`), so they structurally cannot touch
    callback/action/payment/order logic even by mistake.

    A missing row for a given `key` (the overwhelming common case until an
    admin edits something) means "use the code default" — see
    `app.services.button_service.resolve_button`. That keeps stock installs
    byte-for-byte identical to today until an admin actually opens Button
    Manager and changes something.
    """

    __tablename__ = "button_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # Telegram Bot API 9.4+ InlineKeyboardButton.style: "primary" | "success"
    # | "danger", or NULL to mean "use the code's semantic default style /
    # Telegram's own default appearance". Ignored for ReplyKeyboardMarkup
    # buttons (main menu) since KeyboardButton has no such field.
    style: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Native custom Telegram emoji, captured from a MessageEntity the admin
    # sent (see Button Manager, phase 2) — NOT a manually typed id. NULL
    # means "no custom emoji override".
    custom_emoji_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Plain-Unicode fallback/override emoji, prepended to the button text.
    # Used whenever custom_emoji_id is unset, invalid, or the surface
    # doesn't support custom emoji (e.g. reply keyboard buttons).
    unicode_emoji: Mapped[str | None] = mapped_column(String(16), nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    translations: Mapped[list["ButtonTranslation"]] = relationship(
        back_populates="button", cascade="all, delete-orphan"
    )


class ButtonTranslation(TimestampMixin, Base):
    """Per-language button text override. Missing row for a language falls
    back to `app.utils.i18n.t()` with the code's own default locale key (see
    `button_service.resolve_button`) — translations are NOT duplicated here
    until an admin actually edits one, reusing the existing uz/ru/en locale
    files as the real fallback source rather than a second copy."""

    __tablename__ = "button_translations"
    __table_args__ = (UniqueConstraint("button_id", "language", name="uq_button_translation_lang"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    button_id: Mapped[int] = mapped_column(ForeignKey("button_configs.id", ondelete="CASCADE"))
    language: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(String(128))

    button: Mapped["ButtonConfig"] = relationship(back_populates="translations")
