from __future__ import annotations

from app.utils.i18n import t


class DomainError(Exception):
    """Base class for expected business-rule violations.

    Handlers catch this and show a friendly message instead of letting the
    error propagate as an unhandled exception.

    Carries an i18n *key* (+ optional format kwargs) instead of a hardcoded
    message string, so the same error can be rendered in whichever language
    the affected user (customer or admin) actually uses. Customer-facing
    catch sites should call `.localized(lang)` with the right user's `lang`;
    admin-facing catch sites can keep using `str(exc)` unchanged — it
    defaults to Uzbek, since the admin panel is Uzbek-only.
    """

    def __init__(self, key: str, **kwargs: object) -> None:
        self.key = key
        self.kwargs = kwargs
        super().__init__(key)

    def localized(self, lang: str) -> str:
        return t(lang, self.key, **self.kwargs)

    def __str__(self) -> str:  # noqa: D105
        return self.localized("uz")


class OutOfStockError(DomainError):
    pass


class ProductUnavailableError(DomainError):
    pass


class InvalidOrderStateError(DomainError):
    """Raised when an action is attempted on an order in the wrong state,
    e.g. approving an order twice, or uploading proof for an already
    decided order. This is the core defense against duplicate approvals /
    duplicate deliveries / callback spam."""


class DeliveryFailedError(DomainError):
    pass


class RewardUnavailableError(DomainError):
    """Raised when a referral-shop reward no longer exists or was hidden by
    the admin between the customer opening the list and tapping "buy"."""


class InsufficientBalanceError(DomainError):
    """Raised when a customer's referral balance is too low to redeem the
    reward they picked."""
