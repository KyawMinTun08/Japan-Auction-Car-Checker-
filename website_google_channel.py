"""Website Telegram-Channel-invite adapter for JACC Google Login members.

Kept as its own isolated module for the same reason as
website_google_payment_upload.py: a Google Login member has a synthetic
"G_<google sub>" id, never a Telegram numeric id, so it cannot use the
existing /channel bot command (channel_cmd in legacy_bot.py), which is
keyed on a real Telegram chat_id and unbans that id before issuing an
invite. This endpoint skips the unban step entirely -- a Google Login
member has never had a Telegram-side ban recorded against their synthetic
id in the first place -- and just hands back a fresh single-use invite
link for the website to open directly, since this member can never
receive a Telegram DM either.

Verification reuses the same verifyToken Apps Script action and G_/WEB
checks as website_google_payment_upload.py's _verify_member, deliberately
duplicated rather than imported: each Google Login HTTP adapter stays a
self-contained file so a change to one can never accidentally break the
other.
"""
from __future__ import annotations

import logging
import os
import time
from collections import deque
from typing import Any, Awaitable, Callable

import httpx
from aiohttp import web

logger = logging.getLogger(__name__)

GOOGLE_MEMBER_ID_PREFIX = "G_"


class GoogleMemberChannelHttp:
    """Authenticated endpoint issuing a fresh Telegram Channel invite link."""

    def __init__(
        self,
        *,
        sheet_webhook: str,
        create_invite_link: Callable[[], Awaitable[str]],
    ) -> None:
        self.sheet_webhook = str(sheet_webhook or "").strip()
        self.create_invite_link = create_invite_link
        configured = os.environ.get(
            "PAYMENT_CORS_ORIGINS",
            "https://kyawmintun08.github.io,https://japan-auction-car-checker.pages.dev",
        )
        self.allowed_origins = {value.strip() for value in configured.split(",") if value.strip()}
        # An invite link is cheap to request but should not be hammered --
        # same shape of guard as the payment upload adapter's rate limit.
        self.rate_window_seconds = 10 * 60
        self.rate_limit = 5
        self._rate_buckets: dict[str, deque[float]] = {}

    def _headers(self, request: web.Request) -> dict[str, str]:
        origin = request.headers.get("Origin", "")
        headers = {"Cache-Control": "no-store", "Vary": "Origin"}
        if origin in self.allowed_origins:
            headers.update(
                {
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "POST,OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-JACC-User-ID, X-JACC-Device-ID, X-JACC-App",
                }
            )
        return headers

    def _json(self, request: web.Request, payload: dict[str, Any], status: int = 200) -> web.Response:
        return web.json_response(payload, status=status, headers=self._headers(request))

    async def options(self, request: web.Request) -> web.Response:
        return web.Response(status=204, headers=self._headers(request))

    def _allowed_origin(self, request: web.Request) -> bool:
        origin = request.headers.get("Origin", "")
        return not origin or origin in self.allowed_origins

    def _rate_allowed(self, member_id: str) -> bool:
        now = time.monotonic()
        bucket = self._rate_buckets.setdefault(member_id, deque())
        while bucket and now - bucket[0] > self.rate_window_seconds:
            bucket.popleft()
        if len(bucket) >= self.rate_limit:
            return False
        bucket.append(now)
        return True

    async def _verify_member(self, token: str, member_id: str, device_id: str, app_name: str) -> dict[str, Any]:
        if not self.sheet_webhook or not token or not member_id:
            return {"status": "error", "message": "web_access_required"}
        payload: dict[str, Any] = {
            "action": "verifyToken",
            "token": token,
            "userId": member_id,
        }
        if device_id:
            payload["deviceId"] = device_id
        if app_name:
            payload["app"] = app_name
        try:
            async with httpx.AsyncClient(timeout=40, follow_redirects=True) as client:
                response = await client.post(
                    self.sheet_webhook,
                    headers={"Content-Type": "text/plain"},
                    json=payload,
                )
            if response.is_error:
                return {"status": "error", "message": "session_unavailable"}
            data = response.json()
            if not isinstance(data, dict):
                return {"status": "error", "message": "invalid_session"}
            if str(data.get("status", "")).lower() != "ok":
                backend_message = str(data.get("message") or data.get("msg") or "invalid_session")
                if backend_message == "invalid_token":
                    backend_message = "invalid_session"
                return {"status": "error", "message": backend_message}
            returned_id = str(data.get("userId", member_id)).strip()
            if returned_id and returned_id != member_id:
                return {"status": "error", "message": "member_mismatch"}
            if not returned_id.startswith(GOOGLE_MEMBER_ID_PREFIX):
                return {"status": "error", "message": "google_login_required"}
            package = str(data.get("package", "")).strip().upper()
            if package not in {"WEB", "WEB-PROMO"}:
                return {"status": "error", "message": "web_premium_required"}
            # PENDING (first payment not yet approved) is a valid, "ok"
            # verifyToken response for a Google Login member -- Channel
            # access is a paid-member benefit, so require ACTIVE here same
            # as channel_cmd's is_active_member gate for Telegram-origin
            # members.
            status = str(data.get("memberStatus", "")).strip().upper()
            if status != "ACTIVE":
                return {"status": "error", "message": "membership_not_active"}
            return data
        except Exception:
            logger.exception("Google member channel session verification failed")
            return {"status": "error", "message": "session_unavailable"}

    async def invite(self, request: web.Request) -> web.Response:
        if not self._allowed_origin(request):
            return self._json(request, {"status": "error", "code": "ORIGIN_NOT_ALLOWED"}, 403)
        authorization = request.headers.get("Authorization", "")
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        member_id = str(request.headers.get("X-JACC-User-ID", "")).strip()
        if not member_id.startswith(GOOGLE_MEMBER_ID_PREFIX) or len(member_id) > 60:
            return self._json(request, {"status": "error", "code": "MEMBER_ID_REQUIRED"}, 400)
        session = await self._verify_member(
            token,
            member_id,
            str(request.headers.get("X-JACC-Device-ID", "")).strip()[:100],
            str(request.headers.get("X-JACC-App", "web")).strip().lower()[:20],
        )
        if str(session.get("status", "")).lower() != "ok":
            return self._json(request, {"status": "error", "code": session.get("message", "WEB_ACCESS_REQUIRED")}, 401)
        if not self._rate_allowed(member_id):
            return self._json(request, {"status": "error", "code": "RATE_LIMITED"}, 429)

        try:
            invite_url = str(await self.create_invite_link() or "").strip()
        except Exception:
            logger.exception("Google member channel invite creation failed for %s", member_id)
            invite_url = ""
        if not invite_url:
            return self._json(request, {"status": "error", "code": "INVITE_LINK_FAILED"}, 502)
        return self._json(request, {"status": "ok", "inviteUrl": invite_url})


def build_google_member_channel_http_service(
    *,
    sheet_webhook: str,
    create_invite_link: Callable[[], Awaitable[str]],
) -> GoogleMemberChannelHttp | None:
    enabled = os.environ.get("GOOGLE_LOGIN_CHANNEL_ENABLED", "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        logger.info("Google Login channel invite disabled by GOOGLE_LOGIN_CHANNEL_ENABLED")
        return None
    if not str(sheet_webhook or "").strip():
        logger.warning("Google Login channel invite disabled: SHEET_WEBHOOK missing")
        return None
    return GoogleMemberChannelHttp(
        sheet_webhook=sheet_webhook,
        create_invite_link=create_invite_link,
    )
