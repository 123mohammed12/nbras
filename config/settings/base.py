"""
Base settings for Smart Teacher Platform.

Common settings shared across all environments.
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

from decouple import Csv, config

# ─── Paths ────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ─── Security ─────────────────────────────────────────
SECRET_KEY = config("SECRET_KEY", default="super-secret-key-for-smart-teacher-dev-12345")
DEBUG = config("DEBUG", default=False, cast=bool)
ASSESSMENT_SECONDS_PER_QUESTION = config(
    "ASSESSMENT_SECONDS_PER_QUESTION", default=60, cast=int
)
ASSESSMENT_LESSON_MINISTERIAL_TARGET_SIZE = config(
    "ASSESSMENT_LESSON_MINISTERIAL_TARGET_SIZE", default=20, cast=int
)
ASSESSMENT_UNIT_MINISTERIAL_MAX_SIZE = config(
    "ASSESSMENT_UNIT_MINISTERIAL_MAX_SIZE", default=50, cast=int
)
ASSESSMENT_CUSTOM_MAX_QUESTIONS = config(
    "ASSESSMENT_CUSTOM_MAX_QUESTIONS", default=50, cast=int
)
ASSESSMENT_CUSTOM_MAX_DURATION_MINUTES = config(
    "ASSESSMENT_CUSTOM_MAX_DURATION_MINUTES", default=300, cast=int
)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="*", cast=Csv())

# ─── Application Definition ──────────────────────────
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
]

LOCAL_APPS = [
    "apps.accounts",
    "apps.locations",
    "apps.common",
    "apps.curriculum",
    "apps.content",
    "apps.question_bank",
    "apps.ministerial_exams",
    "apps.assessments",
    "apps.attempts",
    "apps.progress",
    "apps.analytics",
    "apps.subscriptions",
    "apps.entitlements",
    "apps.synchronization",
    "apps.imports",
    "apps.media_access",
    "apps.downloads",
    "apps.notifications",
    "apps.control",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ─── Custom User Model ───────────────────────────────
AUTH_USER_MODEL = "accounts.User"

# ─── Middleware ───────────────────────────────────────
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.common.middleware.request_id.RequestIDMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ─── Database ─────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="smart_teacher"),
        "USER": config("DB_USER", default="postgres"),
        "PASSWORD": config("DB_PASSWORD", default=""),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        "OPTIONS": {
            "connect_timeout": 5,
        },
    }
}

# ─── Cache ───────────────────────────────────────────
# If running pytest, use in-memory LocMemCache to isolate tests.
if "pytest" in sys.modules or "test" in sys.argv:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": config("REDIS_URL", default="redis://127.0.0.1:6379/0"),
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "REDIS_CLIENT_KWARGS": {
                    "protocol": 2,
                },
            },
        }
    }

# ─── Password Validation ─────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 4},
    },
]

# ─── Internationalization ─────────────────────────────
LANGUAGE_CODE = "ar"
TIME_ZONE = "Asia/Aden"
USE_I18N = True
USE_TZ = True

# ─── Static / Media ──────────────────────────────────
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── REST Framework ───────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.common.exceptions.handler.custom_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/minute",
        "user": "120/minute",
        "otp_request": "5/hour",
        "otp_verify": "10/hour",
        "guest_create": "10/hour",
        "account_login": "10/hour",
        "registration_complete": "5/hour",
        "password_reset_complete": "5/hour",
        "password_change": "10/hour",
        "password_login": "10/hour",
        "password_login_phone": "10/hour",
        "password_login_ip": "20/hour",
        "password_registration": "5/hour",
        "password_registration_phone": "5/hour",
        "password_registration_ip": "10/hour",
        "password_reset": "5/hour",
        "password_reset_phone": "5/hour",
        "password_reset_ip": "10/hour",
        "token_refresh": "30/hour",
        "locations_public_read": "120/minute",
        "activation_redeem_burst": "5/minute",
        "activation_redeem_sustained": "20/hour",
        "sync_manifest_minute": "30/minute",
        "sync_manifest_hour": "300/hour",
        "sync_operations_minute": "10/minute",
        "sync_operations_hour": "100/hour",
    },
}

# ─── SimpleJWT ────────────────────────────────────────
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_OBTAIN_SERIALIZER": "rest_framework_simplejwt.serializers.TokenObtainPairSerializer",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "JTI_CLAIM": "jti",
}

# ─── CORS ─────────────────────────────────────────────
CORS_ALLOW_ALL_ORIGINS = config("CORS_ALLOW_ALL", default=True, cast=bool)

# ─── Spectacular (Swagger) ────────────────────────────
SPECTACULAR_SETTINGS = {
    "TITLE": "Smart Teacher API",
    "DESCRIPTION": "API documentation for the Smart Teacher educational platform.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1/",
}

# ─── Security Secrets ──────────────────────────────────
OTP_HASH_SECRET = config(
    "OTP_HASH_SECRET",
    default="INSECURE-DEV-OTP-SECRET-CHANGE-IN-PRODUCTION",
)

ACTIVATION_CODE_HMAC_SECRET = config(
    "ACTIVATION_CODE_HMAC_SECRET",
    default="INSECURE-DEV-ACTIVATION-HMAC-SECRET-CHANGE-IN-PRODUCTION",
)

OTP_SETTINGS = {
    "CODE_LENGTH": 6,
    "CODE_EXPIRY_SECONDS": 300,
    "MAX_ATTEMPTS": 5,
    "MAX_RESENDS": 3,
    "RESEND_COOLDOWN_SECONDS": 60,
    "SMS_PROVIDER": config(
        "SMS_PROVIDER",
        default="apps.accounts.providers.fake_provider.FakeOTPProvider",
    ),
}

# ─── Cleanup Retention Settings ───────────────────────
ACCOUNTS_CLEANUP = {
    "OTP_RETENTION_DAYS": config("OTP_RETENTION_DAYS", default=7, cast=int),
    "SESSION_RETENTION_DAYS": config("SESSION_RETENTION_DAYS", default=90, cast=int),
    "DEVICE_INACTIVE_DAYS": config("DEVICE_INACTIVE_DAYS", default=365, cast=int),
}

# ─── Logging ──────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] [{levelname}] [{name}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}

# ─── Idempotency Settings ──────────────────────────────
IDEMPOTENCY_TTL_SECONDS = config("IDEMPOTENCY_TTL_SECONDS", default=86400, cast=int)
IDEMPOTENCY_LOCK_SECONDS = config("IDEMPOTENCY_LOCK_SECONDS", default=60, cast=int)
IDEMPOTENCY_MAX_KEY_LENGTH = config("IDEMPOTENCY_MAX_KEY_LENGTH", default=128, cast=int)
IDEMPOTENCY_MAX_RESPONSE_BYTES = config("IDEMPOTENCY_MAX_RESPONSE_BYTES", default=262144, cast=int)

# ─── Progress & Analytics Settings ─────────────────────
PROGRESS_MASTERY_THRESHOLD = config("PROGRESS_MASTERY_THRESHOLD", default=80, cast=int)
PROGRESS_REVIEW_THRESHOLD = config("PROGRESS_REVIEW_THRESHOLD", default=60, cast=int)
PROGRESS_MIN_MASTERY_QUESTIONS = config("PROGRESS_MIN_MASTERY_QUESTIONS", default=5, cast=int)

ANALYTICS_MIN_INSIGHT_EVIDENCE = config("ANALYTICS_MIN_INSIGHT_EVIDENCE", default=10, cast=int)
ANALYTICS_EVENT_RETENTION_DAYS = config("ANALYTICS_EVENT_RETENTION_DAYS", default=365, cast=int)
QUESTION_QUALITY_POLICY_VERSION = config("QUESTION_QUALITY_POLICY_VERSION", default="ar09-v1")
QUESTION_QUALITY_MIN_SAMPLE_SIZE = config("QUESTION_QUALITY_MIN_SAMPLE_SIZE", default=30, cast=int)
QUESTION_QUALITY_VERY_HIGH_CORRECT_RATE = config("QUESTION_QUALITY_VERY_HIGH_CORRECT_RATE", default="0.95")
QUESTION_QUALITY_VERY_LOW_CORRECT_RATE = config("QUESTION_QUALITY_VERY_LOW_CORRECT_RATE", default="0.20")
QUESTION_QUALITY_HIGH_SKIP_RATE = config("QUESTION_QUALITY_HIGH_SKIP_RATE", default="0.30")
QUESTION_QUALITY_INEFFECTIVE_DISTRACTOR_RATE = config("QUESTION_QUALITY_INEFFECTIVE_DISTRACTOR_RATE", default="0.02")
QUESTION_QUALITY_ANSWER_KEY_ISSUE_RATE = config("QUESTION_QUALITY_ANSWER_KEY_ISSUE_RATE", default="0.60")

# ─── Synchronization Settings ──────────────────────────
SYNC_MAX_BATCH_OPERATIONS = config("SYNC_MAX_BATCH_OPERATIONS", default=50, cast=int)
SYNC_MAX_REQUEST_BYTES = config("SYNC_MAX_REQUEST_BYTES", default=524288, cast=int)
SYNC_MAX_OPERATION_BYTES = config("SYNC_MAX_OPERATION_BYTES", default=8192, cast=int)
SYNC_MAX_RESPONSE_BYTES = config("SYNC_MAX_RESPONSE_BYTES", default=262144, cast=int)
SYNC_MANIFEST_PAGE_SIZE = config("SYNC_MANIFEST_PAGE_SIZE", default=100, cast=int)
SYNC_MANIFEST_MAX_PAGE_SIZE = config("SYNC_MANIFEST_MAX_PAGE_SIZE", default=200, cast=int)

FIREBASE_SERVICE_ACCOUNT_PATH = config("FIREBASE_SERVICE_ACCOUNT_PATH", default="")
NOTIFICATION_EXPIRY_REMINDER_DAYS = config("NOTIFICATION_EXPIRY_REMINDER_DAYS", default=3, cast=int)
