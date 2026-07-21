import discord
from discord.ext import commands
from discord import app_commands
import config
import wavelink
import os
import socket
import asyncio
import random
import aiohttp
from datetime import datetime
from cogs import emoji_loader

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

# ═══════════════════════════════════
# 🚀 Ghostx Community BOT
# 👑 Developer: GHOSTX
# ═══════════════════════════════════

class GhostxBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self._persistent_views_registered = False

    async def setup_hook(self):
        # ── Lavalink connection (via wavelink) ──────────────────────────────
        # Switched from mafic to wavelink: mafic's node handshake was hanging
        # indefinitely even though raw HTTP/WebSocket probes to the same
        # Lavalink server succeeded instantly (confirmed via diagnostics —
        # network, password, and Lavalink itself were never the problem).
        #
        # wavelink kept hanging the exact same way. Root cause: aiohttp's
        # default connector lets the system resolver hand back an AAAA
        # (IPv6) record for the Railway proxy domain, and this container's
        # egress can't actually route IPv6 — so the TCP connect just sits
        # there until asyncio.wait_for's own deadline fires, instead of
        # failing fast. A plain manual probe done at another time can get
        # lucky (cached A record, different resolver order) and connect
        # instantly, which is exactly the discrepancy we saw. Pinning the
        # connector to AF_INET (IPv4-only) removes that variable.
        #
        # We build ONE aiohttp session with that connector, run a quick
        # pre-flight GET over it, and hand that *same* session to
        # wavelink.Node — if the pre-flight also hung, we'd know this is
        # still a networking issue rather than something inside wavelink.
        scheme = "https" if config.LAVALINK_SECURE else "http"
        lavalink_uri = f"{scheme}://{config.LAVALINK_HOST}:{config.LAVALINK_PORT}"

        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        lavalink_session = aiohttp.ClientSession(connector=connector)
        self._lavalink_session = lavalink_session  # keep a ref so it isn't GC'd

        try:
            async with lavalink_session.get(
                f"{lavalink_uri}/version",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                body = await resp.text()
                print(f'🔎 Lavalink pre-flight GET /version -> HTTP {resp.status}: {body}')
        except Exception as e:
            print(f'🔎 Lavalink pre-flight GET /version failed: {e!r}')

        node = wavelink.Node(
            uri=lavalink_uri,
            password=config.LAVALINK_PASSWORD,
            session=lavalink_session,
        )
        last_error = None
        for attempt in range(1, 4):
            try:
                await asyncio.wait_for(
                    wavelink.Pool.connect(nodes=[node], client=self),
                    timeout=30,
                )
                print(f'✅ Lavalink node connected via wavelink ({config.LAVALINK_HOST}:{config.LAVALINK_PORT})')
                break
            except Exception as e:
                last_error = e
                print(f'⚠️ Lavalink connection attempt {attempt}/3 failed: {e!r} (waiting 5s before retry)')
                await asyncio.sleep(5)
        else:
            print(f'⚠️ Lavalink node connection failed after 3 attempts (skipped): {last_error!r}')
            print('   /play and the rest of the music commands won\'t work until a Lavalink server is reachable.')
            print('   See LAVALINK_SETUP.md for how to run one.')

        for file in os.listdir('./cogs'):
            if file.endswith('.py'):
                try:
                    await self.load_extension(f'cogs.{file[:-3]}')
                    print(f'✅ {file}')
                except Exception as e:
                    print(f'❌ {file}: {e}')

        # ─ Persistent views that DON'T depend on per-guild stored config ─
        # (the apply_system panels are guild-specific and need self.guilds
        # to be populated, so they are registered in on_ready instead — see
        # _register_apply_views below.)
        try:
            from cogs.tickets import TicketCreateView, TicketControlView
            from cogs.tickets_shop import ShopTicketDirectView, ShopTicketControlView
            from cogs.verify import VerifyView
            from cogs.create_voice import VoiceControlView
            from cogs.resources import ResourceReviewView, ResourceSubmitPanelView
            from cogs.rules_accept import RulesAcceptView
            from cogs.role_picker import RolePickerView
            self.add_view(TicketCreateView())
            self.add_view(TicketControlView())
            self.add_view(ShopTicketDirectView())
            self.add_view(ShopTicketControlView())
            self.add_view(VerifyView())
            self.add_view(VoiceControlView())
            self.add_view(ResourceReviewView())
            self.add_view(ResourceSubmitPanelView())
            self.add_view(RulesAcceptView())
            self.add_view(RolePickerView())
            print('✅ Persistent views registered (guild-independent)')
        except Exception as e:
            print(f'⚠️ Persistent views: {e}')

        await self.tree.sync()
        print(f'✅ Slash commands synced (global)')

    async def _register_apply_views(self):
        """Registers one persistent ApplyButtonView (Components V2 card) per
        guild/kind that has been configured via /setup apply. Must run after
        the gateway has populated self.guilds, so it's called from on_ready
        rather than setup_hook. Safe to call more than once (e.g. on
        reconnect) since add_view is idempotent per custom_id."""
        try:
            from cogs.apply_system import ApplyButtonView, get_kind_cfg
            count = 0
            for guild in self.guilds:
                for kind in ("staff", "whitelist"):
                    cfg = get_kind_cfg(guild.id, kind)
                    if cfg:
                        self.add_view(ApplyButtonView(kind, cfg))
                        count += 1
            print(f'✅ Apply panel views registered ({count})')
        except Exception as e:
            print(f'⚠️ Apply panel views: {e}')

    async def on_ready(self):
        if not self._persistent_views_registered:
            await self._register_apply_views()
            self._persistent_views_registered = True

        print(f"""
╔══════════════════════════════════╗
║     🚀 {config.BOT_NAME}        ║
║ 👑 Dev: {config.DEVELOPER}               ║
║ 🌐 Server: {config.SERVER_NAME} ║
║ ⚡ {self.user}                   ║
║ 📊 Servers: {len(self.guilds)}                 ║
║ 👥 Users: {len(self.users)}               ║
╚══════════════════════════════════╝
        """)
        # Presence is now owned by cogs/status_rotator.py, which cycles
        # through a list of "Playing ..." statuses continuously.


bot = GhostxBot()

# ────── Basic Commands ──────

@bot.tree.command(name="ping", description="🏓 Check bot reponse speed")
async def ping(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Latency: `{round(bot.latency * 1000)}ms`",
        color=config.EMBED_COLOR
    )
    embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
    await interaction.response.send_message(embed=embed)


HELP_SECTIONS = [
    {
        "key": "admin",
        "title": "Administration",
        "fallback": "🛡️",
        "value": (
            "`/ban` `/kick` `/mute` `/unmute`\n"
            "`/clear` `/lock` `/unlock` `/slowmode`\n"
            "`/warn` `/role add` `/role remove`"
        ),
    },
    {
        "key": "tickets",
        "title": "Tickets",
        "fallback": "🎫",
        "value": "`/ticket setup` `/ticket update` `/ticket remove`\n`/ticket-add` `/ticket-close`",
    },
    {
        "key": "welcome",
        "title": "Welcome, Boost & Subscribe",
        "fallback": "👋",
        "value": (
            "`/welcome setup` `/welcome update` `/welcome remove`\n"
            "`/welcome preview` `/welcome info`\n"
            "`/boost setup` `/boost update` `/boost remove`\n"
            "`/subscribe setup` `/subscribe update` `/subscribe remove`"
        ),
    },
    {
        "key": "applications",
        "title": "Applications",
        "fallback": "📋",
        "value": "`/setup apply` — Staff / Whitelist applications\n`/setup guide` — Full bot setup guide",
    },
    {
        "key": "music",
        "title": "Music",
        "fallback": "🎵",
        "value": (
            "`/play` `/skip` `/stop` `/pause` `/resume`\n"
            "`/queue` `/nowplaying` `/volume` `/loop`\n"
            "`/join` `/leave`"
        ),
    },
    {
        "key": "emojis",
        "title": "Emojis",
        "fallback": "😀",
        "value": (
            "`/emoji steal` — Copy one emoji\n"
            "`/emoji stealall` — Copy all emojis from a server\n"
            "`/emoji uploadzip` — Upload a ZIP of emoji images\n"
            "`/emoji list` `/emoji delete`"
        ),
    },
    {
        "key": "ai",
        "title": "AI",
        "fallback": "🤖",
        "value": "`/ai ask` — Ask the AI anything\n`/ai clear` — Clear your AI conversation history",
    },
    {
        "key": "stats",
        "title": "Server Stats",
        "fallback": "📊",
        "value": (
            "`/serverstats setup` — Create live member/bot/link channels\n"
            "`/serverstats update` — Force refresh now\n"
            "`/serverstats remove` — Remove stat channels"
        ),
    },
    {
        "key": "general",
        "title": "General",
        "fallback": "⭐",
        "value": (
            "`/ping` `/help` `/time` `/report`\n"
            "`/profile` `/random` `/top` `/daily` `/balance`\n"
            "`/rr add` `/rr remove` `/rr list` `/rr clear` — Reaction roles\n"
            "`/rolepicker setup` — Self-assign roles menu"
        ),
    },
    {
        "key": "voice",
        "title": "Voice",
        "fallback": "🎙️",
        "value": "`/voicepanel setup` — Join-to-Create voice system",
    },
    {
        "key": "resources",
        "title": "Resources",
        "fallback": "📦",
        "value": (
            "`/resource submit` — Propose a resource (script/bot/plugin...)\n"
            "`/resource list` `/resource search`\n"
            "`/resource setup` — (Admin) set review/info/panel channels\n"
            "`/resource setpublish` — (Admin) per-category publish channel"
        ),
    },
    {
        "key": "announcements",
        "title": "Announcements",
        "fallback": "📢",
        "value": (
            "`/say` — Send a message/embed as the bot, or DM a role\n"
            "`/notify` — DM every member of a specific role"
        ),
    },
]


def _section_icon() -> str:
    """One consistent, single-color icon for every section. Uses a real,
    standard Unicode emoji (not emoji_loader) because a missing/invalid
    custom emoji here breaks the ENTIRE select menu (Discord rejects all
    options at once with 'Invalid emoji' if even one is malformed).

    NOTE: plain geometric shapes like '▸' are NOT always accepted by
    Discord's emoji validation for SelectOption — using a real emoji
    codepoint avoids that edge case entirely.
    """
    return "🔹"


class HelpSelect(discord.ui.Select):
    def __init__(self):
        icon = _section_icon()
        options = [
            discord.SelectOption(
                label=section["title"],
                value=section["key"],
                emoji=icon,
            )
            for section in HELP_SECTIONS
        ]
        super().__init__(placeholder="📚 اختار قسم الأوامر...", options=options)

    async def callback(self, interaction: discord.Interaction):
        section = next(s for s in HELP_SECTIONS if s["key"] == self.values[0])
        icon = _section_icon()
        embed = discord.Embed(
            title=f"{section['title']}",
            description=section["value"],
            color=config.EMBED_COLOR,
            timestamp=datetime.now(),
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(HelpSelect())


@bot.tree.command(name="help", description="📚 List all bot commands")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title=f"📚 {config.BOT_NAME} — Commands",
        description=(
            f"**{config.SERVER_NAME}** | Developer: **{config.DEVELOPER}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"اختار قسم من المنيو تحت باش تشوف الأوامر ديالو 👇"
        ),
        color=config.EMBED_COLOR,
        timestamp=datetime.now(),
    )
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.set_footer(
        text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}",
        icon_url=bot.user.display_avatar.url,
    )
    await interaction.response.send_message(embed=embed, view=HelpView())


@bot.tree.command(name="report", description="🚨 Report a member")
@app_commands.describe(member="The member to report", reason="Reason for the report")
async def report(interaction: discord.Interaction, member: discord.Member, reason: str):
    embed = discord.Embed(title="🚨 Report", color=config.ERROR_COLOR)
    embed.add_field(name="Reported by", value=interaction.user.mention)
    embed.add_field(name="Reported member", value=member.mention)
    embed.add_field(name="Reason", value=reason)
    embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
    await interaction.channel.send(embed=embed)
    await interaction.response.send_message("✅ Report sent successfully", ephemeral=True)


@bot.tree.command(name="random", description="🎯 اختيار عشوائي — قاد أو مقاد أو من خياراتك")
@app_commands.describe(choices="الخيارات مفصولة بفاصلة — اتركها فارغة لاختيار قاد/مقاد")
async def random_choice(interaction: discord.Interaction, choices: str = ""):
    # ── Default: قاد / مقاد coin flip ──────────────────────────────────────
    if not choices.strip():
        result = random.choice(["قاد ✅", "مقاد ❌"])
        is_yes = result.startswith("قاد")
        color  = config.SUCCESS_COLOR if is_yes else config.ERROR_COLOR
        banner = "🟢 **قاد** — مفعول!" if is_yes else "🔴 **مقاد** — موقوف!"

        embed = discord.Embed(
            title="🎲 Ghostx Random",
            description=(
                f"```\n"
                f"[ قاد ]  vs  [ مقاد ]\n"
                f"```\n"
                f"## {banner}"
            ),
            color=color,
            timestamp=datetime.now(),
        )
        embed.set_author(
            name="Ghostx Community — Random Picker",
            icon_url=bot.user.display_avatar.url,
        )
        embed.set_footer(
            text=f"طلبه: {interaction.user.display_name} | {config.BOT_NAME} | Dev: {config.DEVELOPER}",
            icon_url=interaction.user.display_avatar.url,
        )
        await interaction.response.send_message(embed=embed)
        return

    # ── Custom choices ────────────────────────────────────────────────────────
    options = [c.strip() for c in choices.split(",") if c.strip()]
    if len(options) < 2:
        await interaction.response.send_message(
            embed=discord.Embed(
                description="❌ أدخل خيارين على الأقل مفصولين بفاصلة.",
                color=config.ERROR_COLOR,
            ),
            ephemeral=True,
        )
        return

    result = random.choice(options)
    opts_display = "\n".join(
        f"{'➡️' if o == result else '  •'} {o}" for o in options
    )

    embed = discord.Embed(
        title="🎲 Ghostx Random — Custom Pick",
        description=(
            f"```\n{opts_display}\n```\n"
            f"## ✅ النتيجة: **{result}**"
        ),
        color=config.EMBED_COLOR,
        timestamp=datetime.now(),
    )
    embed.set_author(
        name="Ghostx Community — Random Picker",
        icon_url=bot.user.display_avatar.url,
    )
    embed.set_footer(
        text=f"طلبه: {interaction.user.display_name} | {config.BOT_NAME} | Dev: {config.DEVELOPER}",
        icon_url=interaction.user.display_avatar.url,
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="time", description="🕐 Show current time")
async def time_cmd(interaction: discord.Interaction):
    now = datetime.now()
    await interaction.response.send_message(f"🕐 <t:{int(now.timestamp())}:F>")


# Note: the old standalone "/setup" command now lives at "/setup guide"
# inside cogs/apply_system.py (as part of the "/setup" command group, which
# also holds "/setup apply"). Keeping both under one name would collide,
# so it was moved there instead of staying here.


# ═══════════════════════════════════
# Run Bot
# ═══════════════════════════════════
if __name__ == "__main__":
    bot.run(config.TOKEN)
