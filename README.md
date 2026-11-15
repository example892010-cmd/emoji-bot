# Random Emoji Reaction Bot

A Telegram channel bot that automatically chooses a random emoji reaction for each new channel post.

## What it does

- Detects new channel posts through Telegram webhooks.
- Chooses randomly from a Unicode emoji candidate pool (500+; usually well over 1,000 on current Unicode data).
- Reads the channel's `available_reactions` list and only chooses an enabled standard emoji when Telegram provides an explicit allow-list.
- Uses SQLite to remember processed webhook update IDs, which prevents duplicate work when Telegram retries a delivery.
- Includes `/start`, `/help`, `/status`, `/pool`, and `/id` commands in private chat.
- Includes a Dockerfile and is prepared for a Koyeb web-service deployment.

## Telegram limitation

The current Telegram Bot API documents that non-premium bots can set **up to one reaction per message**. This project therefore adds one random emoji to each post, not 3–5 reactions to the same post. The candidate pool can contain 500+ emojis, but a channel's reaction settings determine which emojis are actually usable. Paid reactions are not used.

## Requirements

- A Telegram bot token from [@BotFather](https://t.me/BotFather).
- A Telegram channel where you can add the bot as an administrator/member.
- Reactions enabled in that channel. Allow the emoji reactions you want the bot to use.
- A public HTTPS endpoint for Telegram webhooks. Koyeb's free web-service tier can be used for a hobby deployment, subject to its sleep/cold-start limitations.

## Deploy free on Koyeb (webhook mode)

1. Create a GitHub repository and upload the contents of this ZIP.
2. Create a free account at [Koyeb](https://app.koyeb.com/).
3. Choose **Create App → Web Service → GitHub** and select this repository.
4. Choose the Dockerfile builder. Use the repository root as the build directory.
5. Select the Free instance in Frankfurt or Washington, D.C. if the option is available to your account.
6. In the service's environment variables, add `BOT_TOKEN`, `WEBHOOK_SECRET`, `DATABASE_PATH=data/bot.sqlite3`, and `LOG_LEVEL=INFO`. You can leave `WEBHOOK_URL` blank for this first deployment.
7. Deploy the service and copy its public HTTPS URL, for example `https://your-service-name.koyeb.app`.
8. Add `WEBHOOK_URL` with that exact public HTTPS URL (no trailing slash) to the service environment, then redeploy. On startup, the app registers the Telegram webhook automatically.
9. Add the bot to your Telegram channel as an administrator. Enable reactions in the channel settings and allow the emoji choices you want it to use.
10. Publish a new channel post. The bot should apply one random allowed emoji reaction.

### Free-tier behavior

Koyeb's free instance is a web service, not a background worker. It scales down to zero after one hour without incoming traffic. A Telegram webhook request can wake the service, so a quiet channel may experience a cold-start delay. The free instance also does not provide a persistent volume. The SQLite file in this project is only a duplicate-update cache; it is not used for long-term settings or channel configuration. This is a hobby/testing setup, not a guaranteed always-on production service.

## Run locally

1. Install Python 3.11 or newer.
2. Create and activate a virtual environment.
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env` and fill in the values. Export those variables in your shell (or use your preferred dotenv runner).
5. Run:

   ```bash
   uvicorn bot:app --host 0.0.0.0 --port 8000
   ```

6. For local Telegram webhook testing, expose port 8000 through an HTTPS tunnel and set `WEBHOOK_URL` to that public HTTPS origin, then restart the app.

## Environment variables

| Variable | Required | Description |
|---|---:|---|
| `BOT_TOKEN` | Yes | Telegram bot token from @BotFather |
| `WEBHOOK_URL` | Yes for deployment | Public HTTPS origin, without trailing slash |
| `WEBHOOK_SECRET` | Yes for deployment | Secret Telegram sends in the webhook header |
| `DATABASE_PATH` | No | SQLite path; defaults to `data/bot.sqlite3` |
| `LOG_LEVEL` | No | Logging level; defaults to `INFO` |

## Troubleshooting

- **Bot does not react:** Make sure it is in the channel, is an administrator if your channel requires that, and that reactions are enabled.
- **No reaction is enabled:** The bot will skip the post if Telegram reports an explicit list with no supported standard emoji reactions.
- **Reaction rejected:** Check that the channel allows standard emoji reactions. The bot logs Telegram API errors in the Koyeb service logs.
- **Webhook not configured:** Check that `WEBHOOK_URL`, `BOT_TOKEN`, and `WEBHOOK_SECRET` are set correctly, then redeploy.
- **Service woke slowly:** This can happen when the free instance has scaled to zero.

## Project structure

```text
random-emoji-reaction-bot/
├── bot.py
├── emoji_pool.py
├── storage.py
├── requirements.txt
├── Dockerfile
├── .env.example
├── .gitignore
├── .dockerignore
└── tests/
    ├── test_emoji_pool.py
    └── test_storage.py
```

## Security

Never commit `.env`, bot tokens, or webhook secrets to GitHub. If a token is exposed, revoke it through @BotFather and create a new one.
