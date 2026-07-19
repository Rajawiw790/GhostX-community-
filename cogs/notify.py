"""
Role Notify — Ghostx Community
────────────────────────────────
/notify — يبعث رسالة فـ الخاص (DM) لكل الأعضاء لي عندهم رول محدد.
صلاحية: Manage Roles
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import asyncio


class Notify(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="notify", description="📨 بعث رسالة فـ الخاص لكل الأعضاء ديال رول محدد")
    @app_commands.describe(
        role="الرول لي بغيتي تبعت لأعضاءه",
        message="النص لي بغيتي تبعتو فـ الخاص",
        embed="بعتها كـ Embed منسق؟ (مفعّل بالدفو)",
        dry_run="غير عد الأعضاء بلا ما تبعت شي حاجة (للتجربة)",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def notify(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        message: str,
        embed: bool = True,
        dry_run: bool = False,
    ):
        members = [m for m in role.members if not m.bot]

        if not members:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ ما كاين حتى عضو (غير بوتات) عندو رول {role.mention}.",
                    color=config.ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        if dry_run:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="🔍 Dry Run",
                    description=(
                        f"غادي يتبعت للـ **{len(members)}** عضو عندهم {role.mention}.\n"
                        f"حيد `dry_run` باش تبعت بجد."
                    ),
                    color=config.WARNING_COLOR,
                ),
                ephemeral=True,
            )
            return

        # ⚠️ إلا الرول كبيرة بزاف (100+)، هاد العملية غادي تدوم دقائق
        # بسبب asyncio.sleep(1) بين كل DM باش نتجنبو rate-limit/spam flag ديال ديسكورد.
        await interaction.response.defer(ephemeral=True, thinking=True)

        dm_embed = None
        if embed:
            dm_embed = discord.Embed(
                title=f"📨 رسالة من {interaction.guild.name}",
                description=message,
                color=config.EMBED_COLOR,
                timestamp=discord.utils.utcnow(),
            )
            dm_embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
            if interaction.guild.icon:
                dm_embed.set_thumbnail(url=interaction.guild.icon.url)

        sent, failed = 0, 0
        for member in members:
            try:
                if dm_embed:
                    await member.send(embed=dm_embed)
                else:
                    await member.send(message)
                sent += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1
            await asyncio.sleep(1)

        result = discord.Embed(
            title="✅ توصلت العملية",
            description=(
                f"**الرول:** {role.mention}\n"
                f"**توصلو:** {sent} عضو\n"
                f"**فشلو (خاص مسكر / حاجبين البوت):** {failed} عضو"
            ),
            color=config.SUCCESS_COLOR,
        )
        result.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.followup.send(embed=result, ephemeral=True)

    @notify.error
    async def notify_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="❌ خاصك صلاحية `Manage Roles` باش تستخدم هاد الكوماند.",
                    color=config.ERROR_COLOR,
                ),
                ephemeral=True,
            )


async def setup(bot):
    await bot.add_cog(Notify(bot))
