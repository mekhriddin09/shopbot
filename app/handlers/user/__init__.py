from aiogram import Router

from app.handlers.user import language, onboarding, orders, referral, reviews, shop, start, stars, support

user_router = Router(name="user_root")
user_router.include_router(start.router)
user_router.include_router(onboarding.router)
user_router.include_router(shop.router)
user_router.include_router(stars.router)
user_router.include_router(orders.router)
user_router.include_router(reviews.router)
user_router.include_router(referral.router)
user_router.include_router(language.router)
user_router.include_router(support.router)

__all__ = ["user_router"]
