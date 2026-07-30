"""Deprecated: the reviews feature no longer uses individual admin-managed
review rows. The "⭐ Reviews" section content is now a single free-text
setting (`reviews_text_uz` / `_ru` / `_en`) edited via Admin panel →
Sozlamalar → "⭐ Sharhlar matni" (see app/handlers/admin/settings.py and
app/keyboards/admin_kb.py). This module is intentionally not registered in
app/handlers/admin/__init__.py and does nothing.
"""
