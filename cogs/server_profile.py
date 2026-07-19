import discord
from discord.ext import commands
from discord import app_commands
import config
import db
from datetime import datetime

SERVER_PROFILE_COLLECTION = "server_profiles"

def load_profiles() -> dict:
    return db.load(SERVER_PROFILE_COLLECTION)

def save_profiles(data: dict):
    db.save(SERVER_PROFILE_COLLECTION, data)


class ServerProfile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.profiles: dict = load_profiles()

    @app_commands.command(name="server-profile-set", description="🏠 إعداد تعريف احترافي للسيرفر")
    @app_commands.describe(
        description="وصف السيرفر",
        banner_url="رابط بانر السيرفر (اختياري)",
        invite="رابط دعوة السيرفر (اختياري)",
        tags="تاغات السيرفر مفصولة بفاصلة مثل: رولبلاي,عربي,ترفيه"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def server_profile_set(
        self,
        interaction: discord.Interaction,
        description: str,
        banner_url: str = None,
        invite: str = None,
        tags: str = None
    ):
        guild_id = str(interaction.guild_id)
        self.profiles[guild_id] = {
            "description": description,
            "banner_url": banner_url,
            "invite": invite,
            "tags": [t.strip() for t in tags.split(",")] if tags else []
        }
        save_profiles(self.profiles)

        embed = discord.Embed(title="✅ تم حفظ تعريف السيرفر", color=config.SUCCESS_COLOR)
        embed.add_field(name="📝 الوصف", value=description[:100], inline=False)
        embed.add_field(name="🏷️ التاغات", value=" | ".join(self.profiles[guild_id]["tags"]) or "—", inline=True)
        embed.add_field(name="🖼️ البانر", value="✅ تم تعيينه" if banner_url else "❌ لا يوجد", inline=True)
        embed.set_footer(text=f"استخدم /server-profile لعرضه | {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="server-profile", description="🏠 عرض تعريف السيرفر الاحترافي")
    async def server_profile(self, interaction: discord.Interaction):
        guild = interaction.guild
        guild_id = str(guild.id)
        profile = self.profiles.get(guild_id, {})

        bots = len([m for m in guild.members if m.bot])
        humans = guild.member_count - bots
        online = len([m for m in guild.members if m.status != discord.Status.offline])

        embed = discord.Embed(
            title=f"🏠 {guild.name}",
            description=profile.get("description") or guild.description or "لا يوجد وصف بعد.",
            color=config.EMBED_COLOR
        )

        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        banner = profile.get("banner_url") or (str(guild.banner.url) if guild.banner else None)
        if banner:
            embed.set_image(url=banner)

        embed.add_field(name="👑 المالك", value=guild.owner.mention if guild.owner else "—", inline=True)
        embed.add_field(name="📅 تأسس", value=f"<t:{int(guild.created_at.timestamp())}:D>", inline=True)
        embed.add_field(name="🚀 مستوى البوست", value=f"Level {guild.premium_tier} ({guild.premium_subscription_count} 🚀)", inline=True)

        embed.add_field(name="👥 الأعضاء", value=f"👤 {humans} بشر | 🤖 {bots} بوت", inline=True)
        embed.add_field(name="🟢 أونلاين", value=str(online), inline=True)
        embed.add_field(name="💬 رومات", value=f"{len(guild.text_channels)} نص | {len(guild.voice_channels)} صوت", inline=True)

        embed.add_field(name="🏷️ رتب", value=str(len(guild.roles) - 1), inline=True)
        embed.add_field(name="😀 إيموجي", value=f"{len(guild.emojis)}/{guild.emoji_limit}", inline=True)

        tags = profile.get("tags", [])
        if tags:
            embed.add_field(name="🔖 التاغات", value=" | ".join(f"`{t}`" for t in tags), inline=False)

        invite = profile.get("invite")
        if invite:
            embed.add_field(name="🔗 الدعوة", value=f"[انضم الآن]({invite})", inline=True)

        embed.add_field(name="🆔 الـ ID", value=f"`{guild.id}`", inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="server-stats", description="📊 إحصائيات السيرفر المفصلة")
    async def server_stats(self, interaction: discord.Interaction):
        guild = interaction.guild
        bots = len([m for m in guild.members if m.bot])
        humans = guild.member_count - bots
        online = len([m for m in guild.members if m.status != discord.Status.offline])
        idle = len([m for m in guild.members if m.status == discord.Status.idle])
        dnd = len([m for m in guild.members if m.status == discord.Status.dnd])
        offline = len([m for m in guild.members if m.status == discord.Status.offline])
        animated_emojis = len([e for e in guild.emojis if e.animated])
        static_emojis = len([e for e in guild.emojis if not e.animated])

        embed = discord.Embed(title=f"📊 إحصائيات {guild.name}", color=config.EMBED_COLOR)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="👥 الأعضاء", value=(
            f"🟢 أونلاين: **{online}**\n"
            f"🟡 بعيد: **{idle}**\n"
            f"🔴 مزعج: **{dnd}**\n"
            f"⚫ أوفلاين: **{offline}**\n"
            f"🤖 بوتات: **{bots}**"
        ), inline=True)

        embed.add_field(name="💬 القنوات", value=(
            f"📝 نصية: **{len(guild.text_channels)}**\n"
            f"🔊 صوتية: **{len(guild.voice_channels)}**\n"
            f"📁 كاتيجوريز: **{len(guild.categories)}**\n"
            f"📢 إعلانية: **{len([c for c in guild.text_channels if c.is_news()])}**"
        ), inline=True)

        embed.add_field(name="😀 الإيموجي", value=(
            f"🖼️ ثابت: **{static_emojis}**\n"
            f"🎞️ متحرك: **{animated_emojis}**\n"
            f"📊 الحد: **{guild.emoji_limit}**"
        ), inline=True)

        embed.add_field(name="🚀 البوست", value=(
            f"المستوى: **{guild.premium_tier}**\n"
            f"البوستات: **{guild.premium_subscription_count}**"
        ), inline=True)

        embed.add_field(name="🏷️ الرتب", value=f"**{len(guild.roles) - 1}**", inline=True)
        embed.add_field(name="📅 عمر السيرفر", value=f"<t:{int(guild.created_at.timestamp())}:R>", inline=True)

        embed.set_footer(text=f"ID: {guild.id} | {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(ServerProfile(bot))
