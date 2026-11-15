from __future__ import annotations

import asyncio
import hmac
import logging
import os
import random
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from emoji_pool import EMOJI_POOL, SAFE_FALLBACK_EMOJIS
from storage import UpdateStore


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("random-emoji-reaction-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/bot.sqlite3").strip()
WEBHOOK_PATH = "/telegram/webhook"
TELEGRAM_API_BASE = "https://api.telegram.org"

if not WEBHOOK_SECRET:
    # This is useful for local tests, but deployments should set a long random
    # secret and keep it private.
    WEBHOOK_SECRET = "local-development-secret-change-me"


class TelegramAPIError(RuntimeError):
    def __init__(self, method: str, description: str, error_code: int = 0) -> None:
        super().__init__(f"Telegram {method} failed ({error_code}): {description}")
        self.method = method
        self.description = description
        self.error_code = error_code


class BotRuntime:
    def __init__(self) -> None:
        self.client: httpx.AsyncClient | None = None
        self.store = UpdateStore(DATABASE_PATH)
        self.process_lock = asyncio.Lock()
        self.chat_cache: dict[int | str, tuple[float, dict[str, Any]]] = {}

    async def api(self, method: str, payload: dict[str, Any]) -> Any:
        if self.client is None:
            raise RuntimeError("HTTP client is not initialized")

        url = f"{TELEGRAM_API_BASE}/bot{BOT_TOKEN}/{method}"
        response = await self.client.post(url, json=payload)
        try:
            body = response.json()
        except ValueError as exc:
            raise TelegramAPIError(method, "Telegram returned invalid JSON", response.status_code) from exc

        if not body.get("ok"):
            description = str(body.get("description", "Unknown Telegram API error"))
            error_code = int(body.get("error_code", response.status_code or 0))
            retry_after = (body.get("parameters") or {}).get("retry_after")
            if error_code == 429 and retry_after:
                delay = min(max(int(retry_after), 1), 20)
                logger.warning("Telegram rate limit on %s; retrying after %s seconds", method, delay)
                await asyncio.sleep(delay)
                response = await self.client.post(url, json=payload)
                try:
                    body = response.json()
                except ValueError as exc:
                    raise TelegramAPIError(method, "Telegram returned invalid JSON after retry", response.status_code) from exc
                if not body.get("ok"):
                    raise TelegramAPIError(
                        method,
                        str(body.get("description", "Unknown Telegram API error")),
                        int(body.get("error_code", response.status_code or 0)),
                    )
            else:
                raise TelegramAPIError(method, description, error_code)

        return body.get("result")

    async def get_chat_info(self, chat_id: int | str) -> dict[str, Any]:
        now = asyncio.get_running_loop().time()
        cached = self.chat_cache.get(chat_id)
        if cached and cached[0] > now:
            return cached[1]

        info = await self.api("getChat", {"chat_id": chat_id})
        if not isinstance(info, dict):
            raise TelegramAPIError("getChat", "Unexpected chat information response")
        self.chat_cache[chat_id] = (now + 300, info)
        return info

    async def choose_reaction(self, chat_id: int | str) -> tuple[str | None, bool]:
        """Return (emoji, allow_list_was_explicit)."""
        info = await self.get_chat_info(chat_id)
        available = info.get("available_reactions")

        if isinstance(available, list):
            allowed_emoji = {
                item.get("emoji")
                for item in available
                if isinstance(item, dict) and item.get("type") == "emoji" and item.get("emoji")
            }
            candidates = [emoji for emoji in EMOJI_POOL if emoji in allowed_emoji]
            if not candidates:
                logger.info("No standard emoji reactions are enabled in chat %s; skipping", chat_id)
                return None, True
            return random.choice(candidates), True

        # If Telegram omits available_reactions, its Bot API documentation says
        # all emoji reactions are allowed. Telegram still validates the exact
        # emoji, so a common-reaction fallback is attempted on REACTION errors.
        return random.choice(EMOJI_POOL), False

    async def react_to_channel_post(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        message_id = message.get("message_id")
        if chat.get("type") != "channel" or chat_id is None or not message_id:
            return

        emoji, explicit_allow_list = await self.choose_reaction(chat_id)
        if emoji is None:
            return

        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}],
            "is_big": False,
        }
        try:
            await self.api("setMessageReaction", payload)
            logger.info("Reacted to channel=%s message=%s with %s", chat_id, message_id, emoji)
        except TelegramAPIError as exc:
            description = exc.description.casefold()
            is_reaction_error = "reaction" in description or "emoji" in description
            if explicit_allow_list or not is_reaction_error:
                raise

            # A candidate outside Telegram's current server-side set can be
            # rejected even when the chat allows all reactions. Try a common
            # standard reaction once rather than silently dropping the post.
            fallback = random.choice(SAFE_FALLBACK_EMOJIS)
            fallback_payload = {
                **payload,
                "reaction": [{"type": "emoji", "emoji": fallback}],
            }
            await self.api("setMessageReaction", fallback_payload)
            logger.info(
                "Initial candidate was not accepted; used fallback %s for channel=%s message=%s",
                fallback,
                chat_id,
                message_id,
            )

    async def handle_update(self, update: dict[str, Any]) -> None:
        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            return

        async with self.process_lock:
            if self.store.has_processed(update_id):
                logger.debug("Ignoring duplicate update %s", update_id)
                return

            channel_post = update.get("channel_post")
            if isinstance(channel_post, dict):
                await self.react_to_channel_post(channel_post)

            message = update.get("message")
            if isinstance(message, dict):
                await self.handle_private_command(message)

            # Persist only after handling succeeds. If Telegram delivery is
            # retried after a temporary failure, the update can be attempted again.
            self.store.mark_processed(update_id)

    async def handle_private_command(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        if chat.get("type") != "private":
            return
        text = str(message.get("text") or "").strip().split(maxsplit=1)[0].lower()
        if not text.startswith("/"):
            return
        command = text.split("@", 1)[0]
        user = message.get("from") or {}
        user_id = user.get("id", "unknown")

        if command in {"/start", "/help"}:
            reply = (
                "👋 I automatically add one random emoji reaction to each new channel post.\n\n"
                "Add me to your channel as an administrator, enable reactions in the channel, "
                "and allow the reactions you want me to use.\n\n"
                "Commands: /status, /pool, /id"
            )
        elif command == "/status":
            reply = (
                "✅ Bot is running.\n"
                f"Emoji candidate pool: {len(EMOJI_POOL)}\n"
                "Reaction mode: one random allowed emoji per new channel post."
            )
        elif command == "/pool":
            reply = f"🎲 Current Unicode emoji candidate pool: {len(EMOJI_POOL)} candidates.\nTelegram's channel reaction settings determine which ones can actually be used."
        elif command == "/id":
            reply = f"Your Telegram user ID: `{user_id}`"
        else:
            return

        await self.api(
            "sendMessage",
            {"chat_id": chat.get("id"), "text": reply, "parse_mode": "Markdown"},
        )


runtime = BotRuntime()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Set it in the deployment environment.")

    runtime.client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0))
    runtime.store.initialize()

    if WEBHOOK_URL:
        if not WEBHOOK_URL.startswith("https://"):
            raise RuntimeError("WEBHOOK_URL must be a public HTTPS URL")
        if not os.getenv("WEBHOOK_SECRET", "").strip():
            raise RuntimeError("WEBHOOK_SECRET must be set for a deployed webhook")
        webhook = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
        await runtime.api(
            "setWebhook",
            {
                "url": webhook,
                "secret_token": WEBHOOK_SECRET,
                "allowed_updates": ["channel_post", "message", "my_chat_member"],
                "drop_pending_updates": False,
            },
        )
        logger.info("Webhook configured: %s", webhook)
    else:
        logger.warning("WEBHOOK_URL is empty; set it to your public HTTPS service URL")

    try:
        await runtime.api(
            "setMyCommands",
            {
                "commands": [
                    {"command": "start", "description": "How the bot works"},
                    {"command": "status", "description": "Show bot status"},
                    {"command": "pool", "description": "Show emoji pool size"},
                    {"command": "id", "description": "Show your Telegram user ID"},
                ]
            },
        )
    except TelegramAPIError:
        logger.exception("Could not register bot commands; continuing")

    try:
        yield
    finally:
        if runtime.client is not None:
            await runtime.client.aclose()
            runtime.client = None


app = FastAPI(
    title="Random Emoji Reaction Bot",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def home() -> dict[str, Any]:
    return {
        "name": "Random Emoji Reaction Bot",
        "status": "ok",
        "emoji_pool_size": len(EMOJI_POOL),
        "webhook_path": WEBHOOK_PATH,
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> JSONResponse:
    if not x_telegram_bot_api_secret_token or not hmac.compare_digest(
        x_telegram_bot_api_secret_token, WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    try:
        update = await request.json()
        if not isinstance(update, dict):
            raise HTTPException(status_code=400, detail="Invalid update body")
        await runtime.handle_update(update)
    except TelegramAPIError as exc:
        logger.exception("Failed to process Telegram update")
        # Non-2xx tells Telegram that delivery did not complete; Telegram may retry.
        raise HTTPException(status_code=503, detail="Telegram API request failed") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected webhook processing error")
        raise HTTPException(status_code=500, detail="Internal error") from exc

    return JSONResponse({"ok": True})
