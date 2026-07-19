import discord
from discord.ext import commands
from discord import app_commands
import config
import db
from datetime import datetime

MESSAGE_LOG_COLLECTION = "message_log_settings"

def load_settings() -> dict:
    return db.load(MESSAGE_LOG_COLLECTION)

def save_settings(settings: dict):
    db.save(MESSAGE_LOG_COLLECTION, settings)


class MessageLog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.settings: dict = load_settings()

    def _get_log_channel(self, guild_id: str):
        return self.settings.get(guild_id, {}).get("log_channel")

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        guild_id = str(message.guild.id)
        log_ch_id = self._get_log_channel(guild_id)
        if not log_ch_id:
            return
        log_ch = message.guild.get_channel(int(log_ch_id))
        if not log_ch:
            return

        embed = discord.Embed(
            title="🗑️ رسالة محذوفة",
            color=config.ERROR_COLOR,
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.add_field(name="📌 الروم", value=message.channel.mention, inline=True)
        embed.add_field(name="👤 العضو", value=message.author.mention, inline=True)
        if message.content:
            embed.add_field(name="📝 المحتوى", value=message.content[:1000], inline=False)
        if message.attachments:
            embed.add_field(name="📎 المرفقات", value="\n".join([a.url for a in message.attachments[:3]]), inline=False)
        embed.set_footer(text=f"ID: {message.author.id}")
        await log_ch.send(embed=embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild:
            return
        if before.content == after.content:
            return
        guild_id = str(before.guild.id)
        log_ch_id = self._get_log_channel(guild_id)
        if not log_ch_id:
            return
        log_ch = before.guild.get_channel(int(log_ch_id))
        if not log_ch:
            return

        embed = discord.Embed(
            title="✏️ رسالة معدّلة",
            color=config.WARNING_COLOR,
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
        embed.add_field(name="📌 الروم", value=before.channel.mention, inline=True)
        embed.add_field(name="🔗 الرسالة", value=f"[انقر هنا]({after.jump_url})", inline=True)
        embed.add_field(name="📝 قبل", value=before.content[:500] or "—", inline=False)
        embed.add_field(name="📝 بعد", value=after.content[:500] or "—", inline=False)
        embed.set_footer(text=f"ID: {before.author.id}")
        await log_ch.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild_id = str(member.guild.id)
        log_ch_id = self._get_log_channel(guild_id)
        if not log_ch_id:
            return
        log_ch = member.guild.get_channel(int(log_ch_id))
        if not log_ch:
            return
        embed = discord.Embed(title="📥 عضو جديد", color=config.SUCCESS_COLOR, timestamp=datetime.utcnow())
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name="👤 العضو", value=member.mention, inline=True)
        embed.add_field(name="🆔 الآيدي", value=f"`{member.id}`", inline=True)
        embed.set_footer(text=f"عدد الأعضاء: {member.guild.member_count}")
        await log_ch.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild_id = str(member.guild.id)
        log_ch_id = self._get_log_channel(guild_id)
        if not log_ch_id:
            return
        log_ch = member.guild.get_channel(int(log_ch_id))
        if not log_ch:
            return
        embed = discord.Embed(title="📤 عضو غادر", color=config.ERROR_COLOR, timestamp=datetime.utcnow())
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name="👤 العضو", value=str(member), inline=True)
        embed.add_field(name="🆔 الآيدي", value=f"`{member.id}`", inline=True)
        embed.set_footer(text=f"عدد الأعضاء: {member.guild.member_count}")
        await log_ch.send(embed=embed)

    @app_commands.command(name="log-setup", description="📋 إعداد روم اللوغ لتتبع الرسائل والأعضاء")
    @app_commands.describe(channel="الروم اللي يتبعث فيه اللوغ")
    @app_commands.default_permissions(manage_guild=True)
    async def log_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild_id = str(interaction.guild_id)
        self.settings[guild_id] = {"log_channel": str(channel.id)}
        save_settings(self.settings)

        embed = discord.Embed(title="✅ تم إعداد اللوغ", color=config.SUCCESS_COLOR)
        embed.add_field(name="📌 روم اللوغ", value=channel.mention, inline=True)
        embed.add_field(name="📊 يتتبع", value="🗑️ الحذف\n✏️ التعديل\n📥 الانضمام\n📤 المغادرة", inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="log-disable", description="🔕 تعطيل نظام اللوغ")
    @app_commands.default_permissions(manage_guild=True)
    async def log_disable(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        if guild_id in self.settings:
            del self.settings[guild_id]
            save_settings(self.settings)
        embed = discord.Embed(title="🔕 تم تعطيل اللوغ", color=config.ERROR_COLOR)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(MessageLog(bot))
