"""
Giveaway System — Ghostx Community
Same Components V2 card design as the apply panels (Container + accent bar).
"""
import discord
from discord.ext import commands
from discord import app_commands
import config
import asyncio
import random
import re
from datetime import datetime, timedelta

# ─── custom emojis (uploaded by ghostx_1x on the FastLife/Ghostx server) ───
EMOJI = {
    "gift": "<:giftingchampion:1530120392583282689>",
    "enter": "<:giftingicon:1530120373780086856>",
    "winner": "<:crown:1530120285989244978>",
    "reroll": "<:refresh:1530119860732956813>",
    "success": "<:squarecheckmark:1530119784878964786>",
    "error": "<:x:1530119812515106928>",
    "warning": "<:warning:1530119891326079118>",
}


def parse_duration(duration: str) -> int:
    """
    يحول نص المدة (مثال: 30s, 10m, 2h, 1d) إلى ثواني
    كيقبل صيغة مركبة زعما: 1h30m
    """
    duration = duration.strip().lower()
    pattern = re.findall(r"(\d+)\s*([smhd])", duration)
    if not pattern:
        raise ValueError("صيغة المدة غير صحيحة")
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return sum(int(value) * units[unit] for value, unit in pattern)


def format_duration(seconds: int) -> str:
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days} يوم")
    if hours:
        parts.append(f"{hours} ساعة")
    if minutes:
        parts.append(f"{minutes} دقيقة")
    if seconds and not parts:
        parts.append(f"{seconds} ثانية")
    return " و".join(parts) if parts else "0 ثانية"


def _msg(emoji: str, title: str, **fields) -> str:
    """Consistent plain-text response layout: emoji + bold title, then fields."""
    lines = [f"{emoji} **{title}**"]
    for label, value in fields.items():
        if value is not None:
            lines.append(f"› **{label}:** {value}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
#  Giveaway card — Components V2 (Container), same design language as the
#  apply panel: title + description + details + optional banner + Section(footer, button).
# ══════════════════════════════════════════════════════════════════════════
class GiveawayCardView(discord.ui.LayoutView):
    def __init__(self, giveaway_id: int, prize: str, end_time: datetime, winners_count: int,
                 banner_url: str = None, footer_text: str = None, description: str = None,
                 participants: set = None):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        self.prize = prize
        self.end_time = end_time
        self.winners_count = winners_count
        self.banner_url = banner_url
        self.footer_text = footer_text or "Good luck to everyone!"
        self.description = description
        self.participants = participants if participants is not None else set()
        self._build()

    def _build(self, *, ended: bool = False, decision_text: str = None, accent: int = None):
        self.clear_items()

        header = f"# {EMOJI['gift']} {self.prize}"
        details = (
            f"**Winners :** {self.winners_count}\n"
            f"**Ends :** <t:{int(self.end_time.timestamp())}:R> (<t:{int(self.end_time.timestamp())}:F>)\n"
            f"**Participants :** {len(self.participants)}"
        )

        items = [discord.ui.TextDisplay(header)]
        if self.description:
            items.append(discord.ui.TextDisplay(self.description))
        items.append(discord.ui.TextDisplay(details))

        if self.banner_url:
            items.append(discord.ui.Separator())
            items.append(discord.ui.MediaGallery(discord.MediaGalleryItem(self.banner_url)))
        items.append(discord.ui.Separator())

        if ended:
            items.append(discord.ui.TextDisplay(decision_text))
        else:
            btn = discord.ui.Button(
                label=f"Enter Giveaway ({len(self.participants)})",
                emoji="<:834134giftingchampion:1530120392583282689>",
                style=discord.ButtonStyle.primary,
                custom_id=f"giveaway_enter_{self.giveaway_id}",
            )
            btn.callback = self.on_enter
            items.append(discord.ui.Section(discord.ui.TextDisplay(self.footer_text), accessory=btn))

        container = discord.ui.Container(*items, accent_color=accent if accent is not None else 0x3B82F6)
        self.add_item(container)

    async def on_enter(self, interaction: discord.Interaction):
        if interaction.user.bot:
            await interaction.response.send_message(f"{EMOJI['error']} البوتات لا يمكنها المشاركة.", ephemeral=True)
            return
        if interaction.user.id in self.participants:
            await interaction.response.send_message(f"{EMOJI['warning']} أنت مشارك بالفعل.", ephemeral=True)
            return

        self.participants.add(interaction.user.id)
        self._build()

        await interaction.response.send_message(
            _msg(EMOJI["enter"], "تم دخول السحب", **{"عدد المشاركين": str(len(self.participants))}),
            ephemeral=True,
        )
        await interaction.message.edit(view=self)

    def mark_ended(self, decision_text: str, accent: int):
        self._build(ended=True, decision_text=decision_text, accent=accent)


class Giveaway(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_giveaways = {}

    @app_commands.command(name="giveaway-start", description="بدء سحب جديد")
    @app_commands.describe(
        prize="اسم الجائزة",
        duration="المدة، مثال: 30s / 10m / 2h / 1d / 1h30m",
        winners="عدد الفائزين",
        channel="الروم (اختياري)",
        banner_url="رابط صورة بانر (اختياري)",
        footer_text="رسالة تبان جنب الزر (اختياري)",
        description="وصف أو تفاصيل زايدة تبان فوق الكارط (اختياري)",
    )
    @app_commands.default_permissions(administrator=True)
    async def giveaway_start(
        self,
        interaction: discord.Interaction,
        prize: str,
        duration: str,
        winners: int = 1,
        channel: discord.TextChannel = None,
        banner_url: str = None,
        footer_text: str = None,
        description: str = None,
    ):
        try:
            duration_seconds = parse_duration(duration)
        except ValueError:
            await interaction.response.send_message(
                f"{EMOJI['error']} صيغة المدة غير صحيحة. استعمل مثال: 30s أو 10m أو 2h أو 1d",
                ephemeral=True
            )
            return

        if duration_seconds <= 0:
            await interaction.response.send_message(f"{EMOJI['error']} المدة خاصها تكون أكبر من صفر.", ephemeral=True)
            return

        if channel is None:
            channel = interaction.channel

        end_time = datetime.now() + timedelta(seconds=duration_seconds)
        giveaway_id = int(datetime.now().timestamp() * 1000)

        view = GiveawayCardView(
            giveaway_id=giveaway_id,
            prize=prize,
            end_time=end_time,
            winners_count=winners,
            banner_url=banner_url,
            footer_text=footer_text,
            description=description,
        )
        message = await channel.send(view=view)

        self.active_giveaways[message.id] = {
            'prize': prize,
            'end_time': end_time,
            'winners': winners,
            'channel_id': channel.id,
            'message_id': message.id,
            'view': view
        }

        await interaction.response.send_message(
            _msg(
                EMOJI["gift"], "تم بدء السحب",
                **{"الروم": channel.mention, "الجائزة": prize, "المدة": format_duration(duration_seconds)},
            ),
            ephemeral=True
        )

        await asyncio.sleep(duration_seconds)
        await self.end_giveaway(message.id)

    async def end_giveaway(self, message_id):
        giveaway = self.active_giveaways.get(message_id)
        if not giveaway:
            return

        channel = self.bot.get_channel(giveaway['channel_id'])
        if not channel:
            return

        try:
            message = await channel.fetch_message(message_id)
        except Exception:
            return

        view = giveaway['view']
        participants = list(view.participants)

        if len(participants) < giveaway['winners']:
            view.mark_ended(f"{EMOJI['warning']} عدد المشاركين غير كافي.", accent=config.ERROR_COLOR)
            await message.edit(view=view)
            del self.active_giveaways[message_id]
            return

        winners_ids = random.sample(participants, min(giveaway['winners'], len(participants)))
        winners_mentions = [f"<@{w}>" for w in winners_ids]

        decision_text = f"{EMOJI['winner']} **الفائزون :**\n{chr(10).join(winners_mentions)}\n\nمبروك للفائزين!"
        view.mark_ended(decision_text, accent=config.SUCCESS_COLOR)
        await message.edit(view=view)

        await channel.send(
            _msg(EMOJI["winner"], "Winner!", **{"الفائزون": ", ".join(winners_mentions), "الجائزة": giveaway['prize']})
        )

        del self.active_giveaways[message_id]

    @app_commands.command(name="giveaway-reroll", description="إعادة سحب فائز")
    @app_commands.describe(message_id="أيدي رسالة السحب")
    @app_commands.default_permissions(administrator=True)
    async def giveaway_reroll(self, interaction: discord.Interaction, message_id: str):
        try:
            await interaction.channel.fetch_message(int(message_id))
        except Exception:
            await interaction.response.send_message(f"{EMOJI['error']} لم يتم العثور على الرسالة.", ephemeral=True)
            return

        members = [m for m in interaction.guild.members if not m.bot]
        if not members:
            await interaction.response.send_message(f"{EMOJI['error']} لا يوجد أعضاء.", ephemeral=True)
            return

        new_winner = random.choice(members)
        await interaction.response.send_message(
            _msg(EMOJI["reroll"], "الفائز الجديد", **{"العضو": new_winner.mention})
        )


async def setup(bot):
    await bot.add_cog(Giveaway(bot))
