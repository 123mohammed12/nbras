"""
PythonAnywhere-specific settings.

Extends production.py with PythonAnywhere platform adaptations:
- DatabaseCache instead of Redis (not available on PythonAnywhere)
- SSL redirect disabled (PythonAnywhere proxy handles SSL)
"""

from .production import *  # noqa: F401, F403

# ─── PythonAnywhere handles SSL at the proxy level ────
# Enabling this causes infinite redirect loops on PythonAnywhere
SECURE_SSL_REDIRECT = False

# ─── Cache — DatabaseCache (no Redis on PythonAnywhere) ──
# Run: python manage.py createcachetable
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache_table",
    }
}
