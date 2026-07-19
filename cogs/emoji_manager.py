import discord
from discord.ext import commands
from discord import app_commands
import config
import aiohttp
import asyncio


class EmojiManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─────────────────────────────────────────────
    # ➕ إضافة إيموجي من رابط
    # ─────────────────────────────────────────────
    @app_commands.command(name="emoji-add", description="➕ إضافة إيموجي من رابط صورة (png/gif)")
    @app_commands.describe(name="اسم الإيموجي", url="رابط الصورة المباشر")
    @app_commands.default_permissions(manage_emojis=True)
    async def emoji_add(self, interaction: discord.Interaction, name: str, url: str):
        await interaction.response.defer(ephemeral=True)

        if not url.startswith("http"):
            await interaction.followup.send("❌ رابط غير صحيح!", ephemeral=True)
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        await interaction.followup.send("❌ فشل تحميل الصورة!", ephemeral=True)
                        return
                    image_data = await resp.read()

            new_emoji = await interaction.guild.create_custom_emoji(
                name=name,
                image=image_data,
                reason=f"أضافه {interaction.user}",
            )

            embed = discord.Embed(title="✅ تم إضافة الإيموجي!", color=config.SUCCESS_COLOR)
            embed.add_field(name="📛 الاسم",    value=f"`:{new_emoji.name}:`",          inline=True)
            embed.add_field(name="🎞️ متحرك",   value="✅" if new_emoji.animated else "❌", inline=True)
            embed.add_field(name="🖼️ الإيموجي", value=str(new_emoji),                    inline=True)
            embed.set_thumbnail(url=str(new_emoji.url))
            embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
            await interaction.followup.send(embed=embed, ephemeral=True)

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ البوت لا يملك صلاحية `Manage Emojis`!", ephemeral=True
            )
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ خطأ: {e}", ephemeral=True)

    # ─────────────────────────────────────────────
    # 🗑️ حذف إيموجي
    # ─────────────────────────────────────────────
    @app_commands.command(name="emoji-delete", description="🗑️ حذف إيموجي من السيرفر")
    @app_commands.describe(name="اسم الإيموجي (بدون :)")
    @app_commands.default_permissions(manage_emojis=True)
    async def emoji_delete(self, interaction: discord.Interaction, name: str):
        emoji = discord.utils.get(interaction.guild.emojis, name=name)
        if not emoji:
            await interaction.response.send_message(
                f"❌ الإيموجي `:{name}:` غير موجود في هذا السيرفر!", ephemeral=True
            )
            return

        await emoji.delete(reason=f"حذفه {interaction.user}")
        embed = discord.Embed(
            title="🗑️ تم الحذف",
            description=f"تم حذف `:{name}:`",
            color=config.ERROR_COLOR,
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────────
    # 📋 قائمة الإيموجي
    # ─────────────────────────────────────────────
    @app_commands.command(name="emoji-list", description="📋 عرض قائمة إيموجي السيرفر")
    async def emoji_list(self, interaction: discord.Interaction):
        emojis = interaction.guild.emojis
        if not emojis:
            await interaction.response.send_message(
                "❌ لا يوجد إيموجي مخصص في هذا السيرفر!", ephemeral=True
            )
            return

        static   = [e for e in emojis if not e.animated]
        animated = [e for e in emojis if e.animated]

        embed = discord.Embed(
            title=f"😀 إيموجي {interaction.guild.name}",
            color=config.EMBED_COLOR,
        )
        embed.add_field(
            name=f"🖼️ ثابت ({len(static)})",
            value=self._build_field(static) or "—",
            inline=False,
        )
        embed.add_field(
            name=f"🎞️ متحرك ({len(animated)})",
            value=self._build_field(animated) or "—",
            inline=False,
        )
        embed.add_field(
            name="📊 المجموع",
            value=f"{len(emojis)} / {interaction.guild.emoji_limit}",
            inline=True,
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

    def _build_field(self, emoji_list, limit: int = 1000) -> str:
        parts, total = [], 0
        for e in emoji_list:
            s = str(e)
            if total + len(s) + 1 > limit - 20:
                remaining = len(emoji_list) - len(parts)
                parts.append(f"**+{remaining}**")
                break
            parts.append(s)
            total += len(s) + 1
        return " ".join(parts)


async def setup(bot):
    await bot.add_cog(EmojiManager(bot))
