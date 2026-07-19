"""
Say Command — Ghostx Community
────────────────────────────────
/say — يبعث البوت رسالة (نص أو Embed) فـ شانل محدد.
صلاحية: Manage Messages
"""

import discord
from discord.ext import commands
from discord import app_commands
import config


class Say(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="say", description="📢 بعث رسالة من البوت فـ شانل محدد أو لأعضاء رول معينة")
    @app_commands.describe(
        message="النص لي بغيتي البوت يبعتو",
        channel="الشانل (فارغ = هاد الشانل الحالي، ما خدامة إلا بلا role)",
        embed="بعتها كـ Embed منسق؟ (ما خدامة إلا بلا role)",
        image_url="رابط صورة تزيدها للإمبيد (اختياري، خدامة غير مع embed=True)",
        role="بدل الشانل: بعت رسالة عادية (بلا embed، فـ الخاص) لكل عضو عندو هاد الرول",
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def say(
        self,
        interaction: discord.Interaction,
        message: str,
        channel: discord.TextChannel = None,
        embed: bool = False,
        image_url: str = None,
        role: discord.Role = None,
    ):
        # ── وضع الرول: رسالة عادية فـ الخاص لكل عضو عندو هاد الرول ──────────
        if role is not None:
            await interaction.response.defer(ephemeral=True)
            members = [m for m in role.members if not m.bot]

            if not members:
                await interaction.followup.send(
                    embed=discord.Embed(
                        description=f"❌ ما كاين حتى عضو عندو رول {role.mention}.",
                        color=config.ERROR_COLOR,
                    ),
                    ephemeral=True,
                )
                return

            sent, failed = 0, 0
            for member in members:
                try:
                    await member.send(message)
                    sent += 1
                except (discord.Forbidden, discord.HTTPException):
                    failed += 1

            await interaction.followup.send(
                embed=discord.Embed(
                    description=(
                        f"✅ تبعتت الرسالة لـ **{sent}** عضو عندو {role.mention}."
                        + (f"\n⚠️ ما تبعتاتش لـ **{failed}** عضو (ساردين الخاص)." if failed else "")
                    ),
                    color=config.SUCCESS_COLOR if sent else config.ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        target = channel or interaction.channel
        perms = target.permissions_for(interaction.guild.me)

        if not perms.send_messages:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ ما عنديش صلاحية نبعت فـ {target.mention}.",
                    color=config.ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        try:
            if embed:
                e = discord.Embed(description=message, color=config.EMBED_COLOR)
                e.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
                if image_url:
                    e.set_image(url=image_url)
                await target.send(embed=e)
            else:
                await target.send(message)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ ما عنديش صلاحية نبعت فـ {target.mention}.",
                    color=config.ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ فشلت العملية: `{e}`",
                    color=config.ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ تبعتت الرسالة فـ {target.mention}",
                color=config.SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    @say.error
    async def say_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="❌ خاصك صلاحية `Manage Messages` باش تستخدم هاد الكوماند.",
                    color=config.ERROR_COLOR,
                ),
                ephemeral=True,
            )


async def setup(bot):
    await bot.add_cog(Say(bot))
