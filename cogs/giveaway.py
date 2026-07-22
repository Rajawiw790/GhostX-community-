import discord
from discord.ext import commands
from discord import app_commands
import config
import asyncio
import random
import re
from datetime import datetime, timedelta


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
    total_seconds = 0
    for value, unit in pattern:
        total_seconds += int(value) * units[unit]

    return total_seconds


def format_duration(seconds: int) -> str:
    """يحول الثواني لنص مفهوم (مثال: 1 يوم 3 ساعات)"""
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


class GiveawayView(discord.ui.View):
    def __init__(self, end_time, prize, winners_count):
        super().__init__(timeout=None)
        self.end_time = end_time
        self.prize = prize
        self.winners_count = winners_count
        self.participants = set()

    @discord.ui.button(label="دخول السحب", style=discord.ButtonStyle.primary, custom_id="enter_giveaway")
    async def enter_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.bot:
            await interaction.response.send_message("البوتات لا يمكنها المشاركة.", ephemeral=True)
            return

        if interaction.user.id in self.participants:
            await interaction.response.send_message("أنت مشارك بالفعل.", ephemeral=True)
            return

        self.participants.add(interaction.user.id)
        button.label = f"دخول السحب ({len(self.participants)})"

        embed = discord.Embed(
            title="تم دخول السحب",
            description=f"أنت مشارك الآن.\nعدد المشاركين: **{len(self.participants)}**",
            color=config.SUCCESS_COLOR
        )
        embed.set_footer(text=config.BOT_NAME)
        await interaction.response.send_message(embed=embed, ephemeral=True)

        await interaction.message.edit(view=self)


class Giveaway(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_giveaways = {}

    @app_commands.command(name="giveaway-start", description="بدء سحب جديد")
    @app_commands.describe(
        prize="اسم الجائزة",
        duration="المدة، مثال: 30s / 10m / 2h / 1d / 1h30m",
        winners="عدد الفائزين",
        channel="الروم (اختياري)"
    )
    @app_commands.default_permissions(administrator=True)
    async def giveaway_start(
        self,
        interaction: discord.Interaction,
        prize: str,
        duration: str,
        winners: int = 1,
        channel: discord.TextChannel = None
    ):
        try:
            duration_seconds = parse_duration(duration)
        except ValueError:
            await interaction.response.send_message(
                "صيغة المدة غير صحيحة. استعمل مثال: 30s أو 10m أو 2h أو 1d",
                ephemeral=True
            )
            return

        if duration_seconds <= 0:
            await interaction.response.send_message("المدة خاصها تكون أكبر من صفر.", ephemeral=True)
            return

        if channel is None:
            channel = interaction.channel

        end_time = datetime.now() + timedelta(seconds=duration_seconds)

        embed = discord.Embed(
            title="سحب جديد",
            description=f"""
## {prize}

**عدد الفائزين:** {winners}
**ينتهي:** <t:{int(end_time.timestamp())}:R> (<t:{int(end_time.timestamp())}:F>)
**المشاركون:** 0

اضغط على الزر أدناه للمشاركة.
""",
            color=config.EMBED_COLOR
        )
        embed.set_footer(text=config.BOT_NAME)

        view = GiveawayView(end_time, prize, winners)
        message = await channel.send(embed=embed, view=view)

        self.active_giveaways[message.id] = {
            'prize': prize,
            'end_time': end_time,
            'winners': winners,
            'channel_id': channel.id,
            'message_id': message.id,
            'view': view
        }

        await interaction.response.send_message(
            f"تم بدء السحب في {channel.mention}\nالجائزة: **{prize}**\nالمدة: {format_duration(duration_seconds)}",
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
            embed = discord.Embed(
                title="انتهى السحب",
                description=f"""
**الجائزة:** {giveaway['prize']}

عدد المشاركين غير كافي.
""",
                color=config.ERROR_COLOR
            )
            embed.set_footer(text=config.BOT_NAME)
            await message.edit(embed=embed, view=None)
            del self.active_giveaways[message_id]
            return

        winners_ids = random.sample(participants, min(giveaway['winners'], len(participants)))
        winners_mentions = [f"<@{w}>" for w in winners_ids]

        embed = discord.Embed(
            title="انتهى السحب",
            description=f"""
**الجائزة:** {giveaway['prize']}

**الفائزون:**
{chr(10).join(winners_mentions)}

مبروك للفائزين!
""",
            color=config.SUCCESS_COLOR
        )
        embed.set_footer(text=config.BOT_NAME)

        await message.edit(embed=embed, view=None)
        await channel.send(
            f"مبروك! {', '.join(winners_mentions)}\n"
            f"فزتوا بـ **{giveaway['prize']}**!"
        )

        del self.active_giveaways[message_id]

    @app_commands.command(name="giveaway-reroll", description="إعادة سحب فائز")
    @app_commands.describe(message_id="أيدي رسالة السحب")
    @app_commands.default_permissions(administrator=True)
    async def giveaway_reroll(self, interaction: discord.Interaction, message_id: str):
        try:
            message = await interaction.channel.fetch_message(int(message_id))
        except Exception:
            await interaction.response.send_message("لم يتم العثور على الرسالة.", ephemeral=True)
            return

        members = [m for m in interaction.guild.members if not m.bot]
        if not members:
            await interaction.response.send_message("لا يوجد أعضاء.", ephemeral=True)
            return

        new_winner = random.choice(members)
        embed = discord.Embed(
            title="إعادة سحب",
            description=f"الفائز الجديد: {new_winner.mention}",
            color=config.EMBED_COLOR
        )
        embed.set_footer(text=config.BOT_NAME)
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Giveaway(bot))
