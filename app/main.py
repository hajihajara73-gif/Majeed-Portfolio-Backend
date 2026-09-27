from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.admin import content as admin_content
from app.api.admin import dashboard as admin_dashboard
from app.api.admin import files as admin_files
from app.api.admin import media as admin_media
from app.api.admin import publish as admin_publish
from app.api.routes import auth, health, public
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.project_name,
    version="0.1.0",
    # No interactive docs in production: the schema is a map of the attack
    # surface, and there is no reason to publish it.
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.environment != "production" else None,
)

if settings.environment == "production":
    # From configuration, never hard-coded. The previous literal
    # `["*.localhost", "localhost"]` would have rejected every real request the
    # moment this was deployed anywhere. `Settings` refuses to start in
    # production unless ALLOWED_HOSTS is set to something that is not localhost.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

# Credentialed CORS cannot use a wildcard origin, so the allowed origins are
# explicit. The CSRF header must be allowed through for the double-submit
# check to work at all.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", settings.csrf_header_name],
    max_age=600,
)


# Registration order matters: Starlette applies `user_middleware` in reverse,
# so the FIRST registered is the OUTERMOST. Headers go first so that even an
# early rejection from the size guard below still carries them.
@app.middleware("http")
async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    """
    Baseline response hardening.

    The API returns JSON only, so a restrictive CSP costs nothing here and
    removes any chance of a response being interpreted as a document.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
    )
    response.headers.setdefault(
        "Cache-Control", "no-store, no-cache, must-revalidate"
    )
    if settings.environment == "production":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.middleware("http")
async def limit_request_size(request: Request, call_next):  # type: ignore[no-untyped-def]
    """
    Refuse an oversized body before anything buffers it.

    Neither uvicorn nor FastAPI caps request size by default, and the field
    length validators only run once the whole payload is already in memory — so
    on an endpoint the public internet can reach, `max_length=5000` is not a
    limit on what an attacker can make the process allocate.

    Content-Length is attacker-supplied, so this is a cheap first gate rather
    than the whole defence: a chunked request that omits the header still meets
    the per-endpoint validators and the upload size check behind it.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit():
        content_type = (request.headers.get("content-type") or "").split(";")[0].strip()
        # Uploads are multipart and legitimately large; nothing else is.
        is_upload = content_type == "multipart/form-data"
        limit = settings.max_request_bytes if is_upload else settings.max_json_bytes
        if int(declared) > limit:
            return JSONResponse(
                status_code=413,
                content={
                    "detail": {
                        "code": "payload_too_large",
                        "message": "That request is too large.",
                    }
                },
            )
    return await call_next(request)


@app.exception_handler(500)
async def internal_error(request: Request, exc: Exception) -> JSONResponse:
    """Never leak a stack trace or driver message to the client."""
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "code": "internal_error",
                "message": "Something went wrong.",
            }
        },
    )


app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)

# The only unauthenticated router. Its abuse controls live in the module.
app.include_router(public.router, prefix=settings.api_prefix)

# Admin CMS. Every one of these routers depends on AdminDep, so authorisation
# is enforced server-side on every request.
for _router in (
    admin_dashboard.router,
    admin_dashboard.messages_router,
    admin_media.router,
    admin_files.router,
    admin_publish.router,
    admin_content.projects_router,
    admin_content.achievements_router,
    admin_content.skills_router,
    admin_content.skill_categories_router,
    admin_content.career_router,
    admin_content.education_router,
    admin_content.expertise_router,
    admin_content.social_router,
    admin_content.singleton_router,
):
    app.include_router(_router, prefix=settings.api_prefix)
