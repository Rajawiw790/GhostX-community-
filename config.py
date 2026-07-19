import os
import shutil

TOKEN = os.getenv("DISCORD_TOKEN", "")  # Set via .env or environment variable

BOT_NAME   = "Ghostx Community"
SERVER_NAME = "Ghostx Community"
DEVELOPER  = "GHOSTX"

GUILD_ID = 0  # Set in /welcome setup, /ticket setup, etc.

EMBED_COLOR   = 0x5865F2
SUCCESS_COLOR = 0x57F287
ERROR_COLOR   = 0xED4245
WARNING_COLOR = 0xFEE75C

# Legacy config fields (kept for cogs that still reference them directly)
WELCOME_CHANNEL_ID     = 0
WELCOME_LOG_CHANNEL_ID = 0
AUTO_ROLE_ID           = 0
WELCOME_BG_URL         = ""
WELCOME_MESSAGE        = ""

TICKET_CATEGORY_ID = 0
SUPPORT_ROLE_ID    = 0
TICKET_LOG_CHANNEL = 0
TICKET_BANNER_URL  = ""

VERIFY_CHANNEL_ID = 0
VERIFIED_ROLE_ID  = 0
VERIFY_BANNER_URL = ""

STAFF_APP_CHANNEL_ID    = 0
STAFF_REVIEW_CHANNEL_ID = 0
STAFF_ROLE_ID           = 0
STAFF_QUESTIONS = [
    "What is your name and age?",
    "How many hours per day can you dedicate to the server?",
    "Do you have previous moderation experience? Explain.",
    "Why do you want to join the staff team?",
    "How would you handle a member who breaks the rules?",
]

CURRENCY_EMOJI = "💰"
FFMPEG_PATH    = shutil.which("ffmpeg") or "ffmpeg"

# ── Lavalink (music) — see LAVALINK_SETUP.md for how to get a node running ──
LAVALINK_HOST     = os.getenv("LAVALINK_HOST", "127.0.0.1")
LAVALINK_PORT     = int(os.getenv("LAVALINK_PORT", "2333"))
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")
LAVALINK_SECURE   = os.getenv("LAVALINK_SECURE", "false").lower() == "true"

# ── MongoDB (all persistent data) — see MONGODB_SETUP.md ──
MONGO_URI     = os.getenv("MONGO_URI", "").strip()
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "ghostx")
