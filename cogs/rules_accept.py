"""
Rules Acceptance Panel — Ghostx Community
────────────────────────────────────────────
بانيل "الموافقة على القوانين" — زر شكل checkbox (خانة اختيار) كيفما فـ
Discord Server Guide، كيعطي رول عند الضغط (بلا حاجة لإعادة الضغط مرتين).

/rulesaccept setup      — (أدمن) حدد الروم والرول والوصف
/rulesaccept customize  — (أدمن) بدّل نص الزر أو الإيموجي
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import db
from cogs import emoji_loader

RULES_ACCEPT_DOC = "rules_accept_settings"


def _settings() -> dict:
    return db.load_doc(RULES_ACCEPT_DOC)


def _save_settings(data: dict) -> None:
    db.save_doc(RULES_ACCEPT_DOC, data)


class RulesAcceptView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        settings = _settings()

        label = settings.get("button_label") or "الموافقة على القوانين"
        emoji = emoji_loader.get_obj("fl_check") or "☑️"

        btn = discord.ui.Button(
            label=label,
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            custom_id="rules_accept_btn",
        )
        btn.callback = self.accept_button
        self.add_item(btn)

    async def accept_button(self, interaction: discord.Interaction):
        settings = _settings()
        role_id = settings.get("role_id")
        e_check = emoji_loader.get("fl_check") or "✅"
        e_x     = emoji_loader.get("fl_x")     or "❌"
        e_warn  = emoji_loader.get("fl_warning") or "⚠️"

        role = interaction.guild.get_role(role_id) if role_id else None
        if not role:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"{e_x} الرول ماكاينش. قول لأدمن يدير `/rulesaccept setup`.",
                    color=config.ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        if role in interaction.user.roles:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"{e_warn} توافقتي على القوانين من قبل!",
                    color=config.WARNING_COLOR,
                ),
                ephemeral=True,
            )
            return

        try:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"{e_check} تمت الموافقة على القوانين! مرحباً بيك فـ {config.SERVER_NAME} 🎉",
                    color=config.SUCCESS_COLOR,
                ),
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"{e_x} ما عنديش صلاحية نعطي هاد الرول — تأكد الرول ديال البوت فوق فـ اللائحة.",
                    color=config.ERROR_COLOR,
                ),
                ephemeral=True,
            )


class RulesAccept(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="rulesaccept-setup", description="☑️ حدد بانيل الموافقة على القوانين")
    @app_commands.describe(
        channel="الروم لي غادي يتبعت فيها البانيل",
        role="الرول لي كيتعطى عند الموافقة",
        description="نص القوانين/الوصف (اختياري)",
    )
    @app_commands.default_permissions(administrator=True)
    async def rulesaccept_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        role: discord.Role,
        description: str = None,
    ):
        settings = _settings()
        settings["role_id"] = role.id
        _save_settings(settings)

        embed = discord.Embed(
            title="📜 القوانين",
            description=description or (
                "قراءة القوانين مسؤوليتك الشخصية. اضغط الزر تحت باش توافق عليها وتحصل على "
                "الوصول الكامل للسيرفر."
            ),
            color=config.EMBED_COLOR,
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

        await channel.send(embed=embed, view=RulesAcceptView())

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ تم تفعيل بانيل الموافقة على القوانين فـ {channel.mention}.\n**الرول:** {role.mention}",
                color=config.SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    @app_commands.command(name="rulesaccept-customize", description="🔘 بدّل نص زر الموافقة")
    @app_commands.describe(label="نص جديد للزر (اختياري)")
    @app_commands.default_permissions(administrator=True)
    async def rulesaccept_customize(self, interaction: discord.Interaction, label: str = None):
        if not label:
            await interaction.response.send_message("❌ خاصك تعطي نص جديد.", ephemeral=True)
            return
        settings = _settings()
        settings["button_label"] = label
        _save_settings(settings)
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ تم تحديث نص الزر لـ: **{label}**\nغادي يبان فـ المرة الجاية لي تدير `/rulesaccept setup`.",
                color=config.SUCCESS_COLOR,
            ),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(RulesAccept(bot))
