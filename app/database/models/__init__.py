"""Import every model so Base.metadata is fully populated for Alembic /
create_all, and so relationship() string references resolve correctly."""
from app.database.models.admin import AdminUser
from app.database.models.admin_log import AdminActionLog
from app.database.models.allowed_phone import AllowedPhoneNumber
from app.database.models.enums import (
    AdminRole,
    DeliveryMode,
    OrderStatus,
    PaymentMethod,
    ReferralCurrency,
    ReferralRedemptionStatus,
    ReferralWithdrawalStatus,
)
from app.database.models.inventory import InventoryCode
from app.database.models.order import Order
from app.database.models.payment import Payment
from app.database.models.product import Product
from app.database.models.provider_log import ProviderLog
from app.database.models.referral import ReferralRedemption, ReferralReward, ReferralWithdrawal
from app.database.models.review import Review
from app.database.models.setting import Setting
from app.database.models.stock_waiter import StockWaiter
from app.database.models.support import SupportRelay
from app.database.models.user import User

__all__ = [
    "AdminUser",
    "AdminActionLog",
    "AllowedPhoneNumber",
    "AdminRole",
    "DeliveryMode",
    "OrderStatus",
    "PaymentMethod",
    "ReferralCurrency",
    "ReferralRedemptionStatus",
    "ReferralWithdrawalStatus",
    "InventoryCode",
    "Order",
    "Payment",
    "Product",
    "ProviderLog",
    "ReferralRedemption",
    "ReferralReward",
    "ReferralWithdrawal",
    "Review",
    "Setting",
    "StockWaiter",
    "SupportRelay",
    "User",
]
