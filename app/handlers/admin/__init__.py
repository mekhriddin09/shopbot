from aiogram import Router

from app.handlers.admin import (
    generic_input,
    inventory,
    menu,
    orders,
    products,
    settings as admin_settings,
    stats,
    support as admin_support,
)

admin_router = Router(name="admin_root")
admin_router.include_router(menu.router)
admin_router.include_router(products.router)
admin_router.include_router(inventory.router)
admin_router.include_router(orders.router)
admin_router.include_router(admin_settings.router)
admin_router.include_router(stats.router)
admin_router.include_router(generic_input.router)
# Registered last: broadly matches any admin "reply" — more specific,
# state-bound handlers above must get first refusal.
admin_router.include_router(admin_support.router)

__all__ = ["admin_router"]
