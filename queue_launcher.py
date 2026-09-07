"""JACC production launcher with Phase 1 queue and member command fixes.

Extends ``completion_launcher`` and safely adds:

    /queue
    /admin and /myadmin
    password-only copy messages for Web members

The large production implementation remains in ``legacy_bot.py``.  This file
only patches runtime entry points before ``legacy_bot.main`` registers them.

NOTE: the Procfile now starts ``phase1_production_launcher.py``, which
imports this file as a module (not as ``__main__``) and layers a few more
patches on top (phase1_healthcheck, membership_approval_patch,
device_reset_patch). This file's own ``mypassword_cmd``/``CommandHandler``
patches below are not the final word on what actually runs — see
PATCH_LOAD_ORDER.md at the repo root for the full chain and which module's
version of each patched name wins.
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from typing import Any

import completion_launcher as _completion
from telegram.ext import ExtBot


# Historically Railway started this file directly as ``__main__`` (it now
# starts phase1_production_launcher.py, which imports this module instead —
# see the note above and PATCH_LOAD_ORDER.md). Kept for the case this file
# is ever run standalone again: expose the running module under its import
# name so phase1_healthcheck patches this exact runtime instead of loading a
# second copy of queue_launcher.
sys.modules.setdefault("queue_launcher", sys.modules[__name__])

_legacy = _completion._legacy
_existing_command_handler = _legacy.CommandHandler
_original_brokers_cmd = _legacy.brokers_cmd
_original_start_cmd = _legacy.start
_original_save_member_to_sheet = _legacy.save_member_to_sheet
_original_set_my_commands = ExtBot.set_my_commands


async def admin_cmd(update, context):
    """Show the admin command panel for /admin and /myadmin."""
    user_id = int(update.effective_user.id)
    if not _legacy.ADMIN_IDS or user_id not in _legacy.ADMIN_IDS:
        await update.effective_message.reply_text(
            "🚫 ဒီ command ကို Admin သာ အသုံးပြုနိုင်ပါတယ်။"
        )
        return

    text = (
        "👑 *JACC Admin Panel*\n\n"
        "📋 `/queue` — Phase 1 request queue\n"
        "✅ `/approve @user 30 WEB` — Member approve\n"
        "👥 `/members` — Member list\n"
        "🚫 `/kick ID` — Member kick\n"
        "🔄 `/renew` — Member renew\n"
        "🔑 `/resetpass @user` — Password reset\n"
        "🆔 `/updateid @user oldID newID` — Telegram ID update\n"
        "💳 `/setqr` — Payment QR setup\n"
        "💾 `/backup` — CSV backup\n"
        "📢 `/broadcast` — Broadcast message\n"
        "👷 `/addbroker` — Broker add\n"
        "🚫 `/kickbroker` — Broker remove\n"
        "📋 `/brokers` — Broker list\n"
        "🏆 `/auctionwon` — Auction won\n"
        "❌ `/auctionlost` — Auction lost\n"
        "💸 `/refunddone` — Refund complete\n"
        "🧾 `/chatlog` — Chat log"
    )
    await update.effective_message.reply_text(text, parse_mode="Markdown")


async def start_admin_router(update, context):
    """Route /start normally and expose /admin aliases without editing legacy_bot."""
    message = update.effective_message
    command = (
        (message.text or "")
        .split(maxsplit=1)[0]
        .split("@", 1)[0]
        .lower()
    )
    if command in {"/admin", "/myadmin"}:
        await admin_cmd(update, context)
        return
    await _original_start_cmd(update, context)


async def mypassword_cmd(update, context):
    """Return the Web password as an exact, password-only plain-text message."""
    user_id = int(update.effective_user.id)
    message = update.effective_message

    if not await _legacy.is_active_member(user_id):
        await message.reply_text(
            "🔒 Member များသာ သုံးနိုင်ပါသည်\n\nMembership ရယူရန် /start နှိပ်ပါ"
        )
        return

    package = await _legacy.get_member_package(user_id)
    if package != "WEB":
        await message.reply_text(
            "🚫 Web Password မရှိပါ\n\n"
            "လက်ရှိ Package: 📱 Standard\n\n"
            "🌐 Web App သုံးဖို့ 💎 Web Premium သို့ Upgrade လုပ်ပါ\n"
            "👉 /renew နှိပ်ပြီး Web Premium ရွေးပါ"
        )
        return

    if not _legacy.SHEET_WEBHOOK:
        await message.reply_text("❌ System error — Admin ကို ဆက်သွယ်ပါ")
        return

    try:
        async with _legacy.httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(
                _legacy.SHEET_WEBHOOK,
                json={"action": "getPassword", "userId": str(user_id), "serverKey": _legacy.SHEET_SERVER_KEY},
                timeout=25,
            )
        response.raise_for_status()
        data = response.json()
        password = str(data.get("password") or "").strip()

        if data.get("status") == "ok" and password:
            await message.reply_text(
                "🔑 သင်၏ Web Password ကို အောက်က message မှာ "
                "သီးခြားပို့ပေးထားပါတယ်။\n\n"
                "🌐 https://kyawmintun08.github.io/Japan-Auction-Car-Checker/\n\n"
                "⚠️ Password ကို မည်သူ့ကိုမျှ မပေးပါနဲ့။"
            )
            await context.bot.send_message(chat_id=user_id, text=password)
            return

        # data.get("message") tells apart unauthorized/expired/no_password/
        # web_access_required, but the reply below collapses all of them to
        # the same generic text -- log the real reason so a repeat of this
        # report is diagnosable from logs, not another screenshot round-trip.
        _legacy.logger.warning(
            "mypassword_cmd: getPassword non-ok user=%s status=%s message=%s",
            user_id, data.get("status"), data.get("message"),
        )
        admin_link = (
            f"\n💬 https://t.me/{_legacy.ADMIN_USERNAME}"
            if _legacy.ADMIN_USERNAME
            else ""
        )
        await message.reply_text(
            f"❌ Password မတွေ့ပါ\n\nAdmin ကို ဆက်သွယ်ပါ{admin_link}"
        )
    except Exception as exc:
        _legacy.logger.error("mypassword patched handler: %s", exc)
        await message.reply_text("❌ Error — Admin ကို ဆက်သွယ်ပါ")


async def save_member_to_sheet(
    user_id: str,
    username: str,
    days: int,
    password: str = "",
    package: str = "CH",
) -> dict:
    """Clean membership values while preserving structured Sheet results."""
    clean_package = str(package or "CH").strip().upper().replace("_", "-")
    aliases = {
        "STANDARD": "CH",
        "CHANNEL": "CH",
        "WEB-PREMIUM": "WEB",
        "PREMIUM": "WEB",
    }
    clean_package = aliases.get(clean_package, clean_package)
    return await _original_save_member_to_sheet(
        str(user_id or "").strip(),
        str(username or "").strip(),
        int(days),
        str(password or "").strip(),
        clean_package,
    )


async def send_approval_dm(
    context,
    member_id: int,
    months: int,
    password: str,
    invite_url: str,
    package: str = "CH",
    expire_date: str = "",
):
    """Send approval details without wrapping the password in quotes or labels."""
    clean_package = str(package or "CH").strip().upper()
    is_web = clean_package.startswith("WEB")
    clean_password = str(password or "").strip()
    expire_date = expire_date or (
        _legacy.datetime.now() + _legacy.timedelta(days=int(months) * 30)
    ).strftime("%d/%m/%Y")

    keyboard_rows = []
    if invite_url:
        keyboard_rows.append([
            _legacy.InlineKeyboardButton("📢 Channel ဝင်ရန်", url=invite_url)
        ])
    if is_web:
        keyboard_rows.append([
            _legacy.InlineKeyboardButton(
                "🌐 Web App ဖွင့်",
                url="https://kyawmintun08.github.io/Japan-Auction-Car-Checker/",
            )
        ])

    package_label = "💎 Web Premium" if is_web else "📱 Standard"
    password_note = (
        "\n🔑 Web Password ကို နောက် message တစ်ခုနဲ့ "
        "သီးခြားပို့ပေးမယ်။\n"
        if is_web
        else ""
    )
    text = (
        "🎉 *Membership Approved!*\n\n"
        f"📦 Package: {package_label}\n"
        f"📅 သက်တမ်း: *{months} လ*\n"
        f"⏰ ကုန်ဆုံးရက်: `{expire_date}`\n"
        f"{password_note}\n"
        "သက်တမ်းတိုးဖို့: /renew\n"
        "ကျေးဇူးတင်ပါတယ် 🙏"
    )

    try:
        sent = await context.bot.send_message(
            chat_id=int(member_id),
            text=text,
            parse_mode="Markdown",
            reply_markup=(
                _legacy.InlineKeyboardMarkup(keyboard_rows)
                if keyboard_rows
                else None
            ),
        )
        try:
            await context.bot.pin_chat_message(
                chat_id=int(member_id),
                message_id=sent.message_id,
                disable_notification=True,
            )
        except Exception as exc:
            _legacy.logger.warning("Approval pin failed: %s", exc)

        if is_web and clean_password:
            await context.bot.send_message(
                chat_id=int(member_id),
                text=clean_password,
            )
    except Exception as exc:
        _legacy.logger.error("Send approval DM patched handler: %s", exc)


def _command_handler_with_queue(command, callback, *args, **kwargs):
    """Register queue, admin aliases, and the patched password handler."""
    if command == "start":
        return _existing_command_handler(
            ["start", "admin", "myadmin"],
            start_admin_router,
            *args,
            **kwargs,
        )
    if command == "mypassword":
        callback = mypassword_cmd
    if command == "brokers":
        command = ["brokers", "brokerfree", "brokerbusy", "queue"]
        callback = brokers_admin_cmd
    return _existing_command_handler(command, callback, *args, **kwargs)


async def _load_phase1_queue(limit: int = 20) -> list[dict[str, Any]]:
    if _legacy.phase1 is None:
        raise _legacy.JaccPhase1Error("PHASE1_NOT_CONFIGURED")

    url = f"{_legacy.phase1._base_url}/rest/v1/jacc_service_requests"
    params = {
        "status": "in.(waiting_broker,offered)",
        "select": (
            "request_code,status,service_type,priority,created_at,form_data"
        ),
        "order": "priority.desc,created_at.asc",
        "limit": str(limit),
    }
    async with _legacy.httpx.AsyncClient(
        timeout=_legacy.phase1._timeout
    ) as client:
        response = await client.get(
            url,
            headers=_legacy.phase1._headers,
            params=params,
        )

    if response.is_error:
        raise _legacy.JaccPhase1Error(
            "Phase 1 queue lookup failed "
            f"({response.status_code}): {response.text[:500]}"
        )
    return list(response.json() or [])


def _queue_text(rows: list[dict[str, Any]]) -> str:
    waiting_count = sum(
        1 for row in rows if row.get("status") == "waiting_broker"
    )
    offered_count = sum(
        1 for row in rows if row.get("status") == "offered"
    )
    lines = [
        "📋 JACC REQUEST QUEUE",
        "",
        f"⏳ Waiting: {waiting_count}",
        f"📨 Offer sent: {offered_count}",
        f"📊 Showing: {len(rows)}",
        "",
    ]

    for index, row in enumerate(rows, start=1):
        form_data = dict(row.get("form_data") or {})
        service = (
            "AUCTION" if row.get("service_type") == "auction" else "OUTSIDE"
        )
        status = (
            "WAITING"
            if row.get("status") == "waiting_broker"
            else "OFFER SENT"
        )
        car_name = str(form_data.get("car_name") or "-")[:60]
        username = str(form_data.get("username") or "-")[:40]
        priority = row.get("priority", 0)
        created_at = str(row.get("created_at") or "").replace("T", " ")[:16]
        lines.extend(
            [
                (
                    f"{index}. {row.get('request_code', '-')} | "
                    f"{service} | {status} | P{priority}"
                ),
                f"   🚗 {car_name}",
                f"   👤 {username} | 🕒 {created_at}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


async def brokers_admin_cmd(update, context):
    """Keep existing broker commands and serve the admin-only /queue view."""
    message = update.effective_message
    command = (
        (message.text or "")
        .split(maxsplit=1)[0]
        .split("@", 1)[0]
        .lower()
    )

    if command != "/queue":
        await _original_brokers_cmd(update, context)
        return

    user = update.effective_user
    if not _legacy.ADMIN_IDS or user.id not in _legacy.ADMIN_IDS:
        await message.reply_text("❌ Admin သာ သုံးနိုင်ပါတယ်")
        return

    try:
        rows = await _load_phase1_queue()
    except _legacy.JaccPhase1Error as exc:
        _legacy.logger.warning("Phase 1 /queue unavailable: %s", exc)
        await message.reply_text("❌ Queue data မရသေးပါ — ခဏပြန်စမ်းပါ")
        return
    except Exception:
        _legacy.logger.exception("Phase 1 /queue failed")
        await message.reply_text("❌ Queue စစ်ဆေးမှု မအောင်မြင်ပါ")
        return

    if not rows:
        await message.reply_text("✅ Queue ထဲမှာ စောင့်နေတဲ့ Request မရှိပါ")
        return

    await message.reply_text(_queue_text(rows))


async def _set_my_commands_with_admin_tools(self, commands, *args, **kwargs):
    """Ensure /admin and /queue appear in admin Telegram command scopes."""
    scope = kwargs.get("scope")
    chat_id = getattr(scope, "chat_id", None)
    try:
        is_admin_scope = int(chat_id) in _legacy.ADMIN_IDS
    except (TypeError, ValueError):
        is_admin_scope = False

    patched = list(commands)
    existing = {getattr(item, "command", "") for item in patched}
    if is_admin_scope:
        if "admin" not in existing:
            patched.append(_legacy.BotCommand("admin", "👑 Admin Panel"))
        if "queue" not in existing:
            patched.append(
                _legacy.BotCommand("queue", "📋 Request Queue ကြည့်ရန် (Admin)")
            )

    return await _original_set_my_commands(self, patched, *args, **kwargs)


# ``legacy_bot.main`` resolves these globals when registering handlers.
_legacy.CommandHandler = _command_handler_with_queue
_legacy.brokers_cmd = brokers_admin_cmd
_legacy.mypassword_cmd = mypassword_cmd
_legacy.save_member_to_sheet = save_member_to_sheet
_legacy.send_approval_dm = send_approval_dm
ExtBot.set_my_commands = _set_my_commands_with_admin_tools

# Load Phase 1 health/backup commands and the phone-friendly restore patch
# before completion_launcher starts legacy_bot.main and registers handlers.
import phase1_healthcheck as _phase1_healthcheck  # noqa: F401,E402
import phase1_restore_latest as _phase1_restore_latest  # noqa: F401,E402
import membership_approval_patch as _membership_approval_patch  # noqa: F401,E402


async def main() -> None:
    await _completion.main()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _legacy.logger.info("Bot stopped by user (Ctrl+C)")
    except Exception as exc:
        _legacy.logger.error("FATAL CRASH: %s", exc)
        _legacy.logger.error(traceback.format_exc())
        raise
