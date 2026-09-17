"""Automatic UZCARD/Humo payment verification.

Card alerts arrive from @CardXabarBot through a Telegram Business
connection (see app/handlers/business.py), are parsed here, and matched
against orders awaiting payment by their unique expected amount.
"""
from app.services.card_payment.parser import CardNotification, parse_card_message

__all__ = ["CardNotification", "parse_card_message"]
