import asyncio

from bot import BotRuntime


def test_explicit_allow_list_limits_reaction_choice():
    runtime = BotRuntime()

    async def fake_get_chat_info(chat_id):
        return {
            "id": chat_id,
            "available_reactions": [
                {"type": "emoji", "emoji": "👍"},
                {"type": "custom_emoji", "custom_emoji_id": "123"},
            ],
        }

    runtime.get_chat_info = fake_get_chat_info
    chosen, explicit = asyncio.run(runtime.choose_reaction(-100123))

    assert chosen == "👍"
    assert explicit is True


def test_empty_allow_list_skips_reaction():
    runtime = BotRuntime()

    async def fake_get_chat_info(chat_id):
        return {"id": chat_id, "available_reactions": []}

    runtime.get_chat_info = fake_get_chat_info
    chosen, explicit = asyncio.run(runtime.choose_reaction(-100123))

    assert chosen is None
    assert explicit is True


def test_missing_allow_list_uses_large_random_pool():
    runtime = BotRuntime()

    async def fake_get_chat_info(chat_id):
        return {"id": chat_id}

    runtime.get_chat_info = fake_get_chat_info
    chosen, explicit = asyncio.run(runtime.choose_reaction(-100123))

    assert chosen is not None
    assert chosen in runtime_pool()
    assert explicit is False


def runtime_pool():
    from emoji_pool import EMOJI_POOL

    return EMOJI_POOL


def test_channel_post_sets_exactly_one_reaction():
    runtime = BotRuntime()
    captured = []

    async def fake_choose_reaction(chat_id):
        return "👍", True

    async def fake_api(method, payload):
        captured.append((method, payload))
        return True

    runtime.choose_reaction = fake_choose_reaction
    runtime.api = fake_api

    asyncio.run(
        runtime.react_to_channel_post(
            {
                "message_id": 45,
                "chat": {"id": -100555, "type": "channel"},
            }
        )
    )

    assert len(captured) == 1
    method, payload = captured[0]
    assert method == "setMessageReaction"
    assert payload["chat_id"] == -100555
    assert payload["message_id"] == 45
    assert payload["reaction"] == [{"type": "emoji", "emoji": "👍"}]


def test_duplicate_webhook_update_is_processed_once(tmp_path):
    from storage import UpdateStore

    runtime = BotRuntime()
    runtime.store = UpdateStore(str(tmp_path / "updates.sqlite3"))
    runtime.store.initialize()
    handled = []

    async def fake_react(message):
        handled.append(message["message_id"])

    runtime.react_to_channel_post = fake_react
    update = {
        "update_id": 9001,
        "channel_post": {
            "message_id": 88,
            "chat": {"id": -100555, "type": "channel"},
        },
    }

    asyncio.run(runtime.handle_update(update))
    asyncio.run(runtime.handle_update(update))

    assert handled == [88]
