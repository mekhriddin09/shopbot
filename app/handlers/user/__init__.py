from aiogram import Router

from app.handlers.user import language, orders, reviews, shop, start, support

user_router = Router(name="user_root")
user_router.include_router(start.router)
user_router.include_router(shop.router)
user_router.include_router(orders.router)
user_router.include_router(reviews.router)
user_router.include_router(language.router)
user_router.include_router(support.router)

__all__ = ["user_router"]
