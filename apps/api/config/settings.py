"""ScaleVexo CRM settings.

Every value that differs between laptops and servers comes from environment
variables. See the .env.example file in the repository root.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


ON_VERCEL = bool(env("VERCEL"))  # set by Vercel in builds and functions

SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", not ON_VERCEL)
if ON_VERCEL and SECRET_KEY.startswith("dev-only"):
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY in the Vercel project settings.")
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]
# Vercel's own domains for this project (production and per-deployment URLs).
for _host in {env("VERCEL_PROJECT_PRODUCTION_URL"), env("VERCEL_BRANCH_URL"), env("VERCEL_URL")} - {None, ""}:
    ALLOWED_HOSTS.append(_host)
    CSRF_TRUSTED_ORIGINS.append(f"https://{_host}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "modules.common",
    "modules.identity",
    "modules.crm",
    "modules.work",
    "modules.support",
    "modules.automation",
    "modules.reporting",
    "modules.ai",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

# Database: PostgreSQL is the supported database. SQLite is only a
# convenience for a quick laptop trial (DB_ENGINE=sqlite).
if env("DB_ENGINE", "postgres") == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "local.sqlite3",
        }
    }
elif env("DATABASE_URL"):
    # Hosted PostgreSQL given as one URL (Neon on Vercel): postgres://user:pass@host/db?sslmode=require
    from urllib.parse import parse_qsl, unquote, urlsplit

    _url = urlsplit(env("DATABASE_URL"))
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(_url.path.lstrip("/")),
            "USER": unquote(_url.username or ""),
            "PASSWORD": unquote(_url.password or ""),
            "HOST": _url.hostname,
            "PORT": _url.port or 5432,
            "OPTIONS": dict(parse_qsl(_url.query)),
            # Serverless functions are short-lived and Neon's pooled URL is PgBouncer in transaction mode.
            "CONN_MAX_AGE": 0,
            "DISABLE_SERVER_SIDE_CURSORS": True,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", "scalevexo"),
            "USER": env("POSTGRES_USER", "scalevexo"),
            "PASSWORD": env("POSTGRES_PASSWORD", "scalevexo"),
            "HOST": env("POSTGRES_HOST", "localhost"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = env("DJANGO_STATIC_ROOT", str(BASE_DIR / "staticfiles"))

# Sessions and cookies (same-origin SPA)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 12
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # the SPA reads it to send X-CSRFToken
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", not DEBUG)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["modules.identity.auth.MembershipSessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["modules.identity.auth.IsActiveMember"],
    "DEFAULT_PAGINATION_CLASS": "modules.common.pagination.StandardPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "modules.common.errors.exception_handler",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

# Privileged users (CEO/owner and administrators) must use MFA when true.
REQUIRE_MFA_FOR_PRIVILEGED = env_bool("REQUIRE_MFA_FOR_PRIVILEGED", not DEBUG)

# AI provider configuration (CRM12). Keys live only in the environment.
AI_ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", "")
AI_ANTHROPIC_URL = env("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")
AI_REQUEST_TIMEOUT_SECONDS = float(env("AI_REQUEST_TIMEOUT_SECONDS", "30"))

# Shared secret for /api/cron/rules, which runs the rules where no worker process can stay up (Vercel).
CRON_SECRET = env("CRON_SECRET", "")

# Public base URL used in invitation links.
APP_BASE_URL = env("APP_BASE_URL", "http://localhost:5173")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
