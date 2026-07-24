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
        "emoji_name": "fl_admin",
        "fallback": "🛡️",
        "value": (
            "› `/ban` `/kick` — طرد أو حذف عضو\n"
            "› `/mute` `/unmute` — كتم أو رفع الكتم\n"
            "› `/warn` — إعطاء تحذير\n"
            "› `/clear` — مسح رسائل\n"
            "› `/lock` `/unlock` — قفل أو فتح الروم\n"
            "› `/slowmode` — ضبط السلو مود\n"
            "› `/role add` `/role remove` — إدارة الرتب"
        ),
    },
    {
        "key": "tickets",
        "title": "Tickets",
        "emoji_name": "fl_ticket",
        "fallback": "🎫",
        "value": (
            "› `/ticket setup` — تفعيل نظام التذاكر\n"
            "› `/ticket update` — تعديل الإعدادات\n"
            "› `/ticket remove` — إلغاء النظام\n"
            "› `/ticket-add` — إضافة عضو للتذكرة\n"
            "› `/ticket-close` — إغلاق التذكرة"
        ),
    },
    {
        "key": "welcome",
        "title": "Welcome, Boost & Subscribe",
        "emoji_name": "fl_home",
        "fallback": "👋",
        "value": (
            "› `/welcome setup` `/welcome update` `/welcome remove`\n"
            "› `/welcome preview` `/welcome info`\n"
            "› `/boost setup` `/boost update` `/boost remove`\n"
            "› `/subscribe setup` `/subscribe update` `/subscribe remove`"
        ),
    },
    {
        "key": "applications",
        "title": "Applications",
        "emoji_name": "fl_application",
        "fallback": "📋",
        "value": (
            "› `/setup apply` — طلبات Staff / Whitelist\n"
            "› `/setup guide` — دليل إعداد البوت الكامل"
        ),
    },
    {
        "key": "music",
        "title": "Music",
        "emoji_name": "fl_music",
        "fallback": "🎵",
        "value": (
            "› `/play` — تشغيل أو إضافة أغنية\n"
            "› `/skip` `/stop` — تخطي أو إيقاف\n"
            "› `/pause` `/resume` — إيقاف مؤقت أو استئناف\n"
            "› `/queue` `/nowplaying` — عرض القائمة أو الأغنية الحالية\n"
            "› `/volume` `/loop` — الصوت والتكرار\n"
            "› `/join` `/leave` — دخول أو خروج الروم الصوتي"
        ),
    },
    {
        "key": "emojis",
        "title": "Emojis",
        "emoji_name": "fl_emojis",
        "fallback": "😀",
        "value": (
            "› `/emoji steal` — نسخ إيموجي واحد\n"
            "› `/emoji stealall` — نسخ كل إيموجيات سيرفر آخر\n"
            "› `/emoji uploadzip` — رفع ZIP فيه صور إيموجيات\n"
            "› `/emoji list` `/emoji delete` — عرض أو حذف"
        ),
    },
    {
        "key": "ai",
        "title": "AI",
        "emoji_name": "fl_ai",
        "fallback": "🤖",
        "value": (
            "› `/ai ask` — اسأل الـ AI أي سؤال\n"
            "› `/ai clear` — امسح سجل محادثتك"
        ),
    },
    {
        "key": "stats",
        "title": "Server Stats",
        "emoji_name": "fl_stats",
        "fallback": "📊",
        "value": (
            "› `/serverstats setup` — إنشاء رومات إحصائيات حية\n"
            "› `/serverstats update` — تحديث فوري\n"
            "› `/serverstats remove` — حذف الرومات"
        ),
    },
    {
        "key": "general",
        "title": "General",
        "emoji_name": "fl_star",
        "fallback": "⭐",
        "value": (
            "› `/ping` `/help` `/time` `/report`\n"
            "› `/profile` `/random` `/top` `/daily` `/balance`\n"
            "› `/rr add` `/rr remove` `/rr list` `/rr clear` — رتب بالرياكشن\n"
            "› `/rolepicker setup` — قائمة رتب ذاتية"
        ),
    },
    {
        "key": "voice",
        "title": "Voice",
        "emoji_name": "fl_voice",
        "fallback": "🎙️",
        "value": "› `/voicepanel setup` — نظام Join-to-Create الصوتي",
    },
    {
        "key": "resources",
        "title": "Resources",
        "emoji_name": "fl_resources",
        "fallback": "📦",
        "value": (
            "› `/resource submit` — اقترح مورد (سكريبت/بوت/بلوگين...)\n"
            "› `/resource list` `/resource search`\n"
            "› `/resource setup` — (Admin) ضبط رومات المراجعة\n"
            "› `/resource setpublish` — (Admin) روم نشر لكل كاتيغوري"
        ),
    },
    {
        "key": "announcements",
        "title": "Announcements",
        "emoji_name": "fl_announcement",
        "fallback": "📢",
        "value": (
            "› `/say` — إرسال رسالة/embed باسم البوت، أو DM لرتبة\n"
            "› `/notify` — DM لكل أعضاء رتبة معينة"
        ),
    },
]


def _section_emoji_obj(section: dict):
    """Emoji object for use inside a SelectOption (emoji=...). Falls back
    to the section's plain Unicode emoji if the custom Application Emoji
    isn't loaded yet (or isn't mapped) — never returns something invalid,
    since a bad emoji on ANY option breaks the whole select menu."""
    name = section.get("emoji_name")
    if name:
        obj = emoji_loader.get_obj(name)
        if obj:
            return obj
    return section["fallback"]


def _section_emoji_str(section: dict) -> str:
    """Emoji as printable text, for use inside a TextDisplay / markdown
    body (e.g. '<:fl_home:123...>'). Falls back to the Unicode emoji."""
    name = section.get("emoji_name")
    if name:
        text = emoji_loader.get(name)
        if text:
            return text
    return section["fallback"]


class HelpSelect(discord.ui.Select):
    def __init__(self, active_key: str | None = None):
        options = [
            discord.SelectOption(
                label=section["title"],
                value=section["key"],
                emoji=_section_emoji_obj(section),
                default=(section["key"] == active_key),
            )
            for section in HELP_SECTIONS
        ]
        super().__init__(
            placeholder="📚 اختار قسم الأوامر...",
            options=options,
            custom_id="help_section_select",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=HelpLayoutView(active_key=self.values[0]))


class HelpLayoutView(discord.ui.LayoutView):
    """Components V2 card — same visual language as the apply panel
    (Container + TextDisplay + Separator + Section w/ thumbnail accessory),
    instead of a classic embed."""

    def __init__(self, active_key: str | None = None):
        super().__init__(timeout=180)

        section = next((s for s in HELP_SECTIONS if s["key"] == active_key), None)

        header_text = (
            f"# 📚 {config.BOT_NAME} — Commands\n"
            f"**{config.SERVER_NAME}** | Developer: **{config.DEVELOPER}**"
        )
        header_section = discord.ui.Section(
            discord.ui.TextDisplay(header_text),
            accessory=discord.ui.Thumbnail(media=bot.user.display_avatar.url),
        )

        if section:
            body_text = f"## {_section_emoji_str(section)} {section['title']}\n{section['value']}"
        else:
            body_text = "اختار قسم من المنيو تحت باش تشوف الأوامر ديالو 👇"

        footer_text = f"-# {config.BOT_NAME} | Dev: {config.DEVELOPER}"

        items = [
            header_section,
            discord.ui.Separator(),
            discord.ui.TextDisplay(body_text),
            discord.ui.Separator(),
            discord.ui.ActionRow(HelpSelect(active_key=active_key)),
            discord.ui.TextDisplay(footer_text),
        ]
        container = discord.ui.Container(*items, accent_color=config.EMBED_COLOR)
        self.add_item(container)


@bot.tree.command(name="help", description="📚 List all bot commands")
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(view=HelpLayoutView())


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
