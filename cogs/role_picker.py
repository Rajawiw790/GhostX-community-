"""
Role Picker — Ghostx Community
────────────────────────────────
نظام "pick role" — منيو (dropdown select) العضو يختار منها الرولات لي بغا،
وكيتزادو/كيتحيدو أوتوماتيك، بلا ريأكشنات وبلا IDs مكتوبة يدوياً.

/rolepicker addrole    — (أدمن) زيد رول للمنيو
/rolepicker removerole — (أدمن) حيد رول من المنيو
/rolepicker list        — (أدمن) شوف الرولات المضافة
/rolepicker setup       — (أدمن) بعث/رفريش البانيل فـ روم

ملاحظة: المنيو محدود لـ 25 خيار (حد الديسكورد ديال Select).
إلا زدتي/حيدتي رول بعد ما تكون بعثتي البانيل، خاصك تعاود `/rolepicker setup`
باش يترفريش بآخر الرولات.
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import db

SETTINGS_DOC = "role_picker_settings"


def _settings() -> dict:
    return db.load_doc(SETTINGS_DOC)


def _save_settings(data: dict) -> None:
    db.save_doc(SETTINGS_DOC, data)


class RolePickerSelect(discord.ui.Select):
    def __init__(self, roles_config: list[dict]):
        options = []
        for r in roles_config[:25]:
            options.append(
                discord.SelectOption(
                    label=r["label"][:100],
                    value=str(r["role_id"]),
                    description=(r.get("description") or "")[:100] or None,
                    emoji=r.get("emoji") or None,
                )
            )
        super().__init__(
            placeholder="اختار الرولات لي بغيتي... (يقدر يكون بزّاف)",
            min_values=0,
            max_values=len(options) if options else 1,
            options=options,
            custom_id="role_picker_select",
        )
        self._configured_ids = {int(r["role_id"]) for r in roles_config}

    async def callback(self, interaction: discord.Interaction):
        selected_ids = {int(v) for v in self.values}
        member = interaction.user
        guild = interaction.guild

        to_add, to_remove = [], []
        for role_id in self._configured_ids:
            role = guild.get_role(role_id)
            if not role:
                continue
            has_it = role in member.roles
            wants_it = role_id in selected_ids
            if wants_it and not has_it:
                to_add.append(role)
            elif not wants_it and has_it:
                to_remove.append(role)

        try:
            if to_add:
                await member.add_roles(*to_add)
            if to_remove:
                await member.remove_roles(*to_remove)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="❌ ما عنديش صلاحية نبدل هاد الرولات — تأكد رول البوت فوق فـ اللائحة.",
                    color=config.ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        lines = []
        if to_add:
            lines.append("✅ تزادو: " + ", ".join(r.mention for r in to_add))
        if to_remove:
            lines.append("➖ تحيدو: " + ", ".join(r.mention for r in to_remove))
        if not lines:
            lines.append("ما تبدل شي حاجة.")

        await interaction.response.send_message(
            embed=discord.Embed(description="\n".join(lines), color=config.SUCCESS_COLOR),
            ephemeral=True,
        )


class RolePickerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        settings = _settings()
        roles_config = settings.get("roles", [])
        if roles_config:
            self.add_item(RolePickerSelect(roles_config))


class RolePicker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    rolepicker_group = app_commands.Group(
        name="rolepicker",
        description="🎭 نظام اختيار الرولات (self-assign)",
        default_permissions=discord.Permissions(manage_roles=True),
    )

    @rolepicker_group.command(name="addrole", description="➕ زيد رول لمنيو الاختيار")
    @app_commands.describe(
        role="الرول لي بغيتي تزيدو",
        label="الاسم لي غادي يبان فـ المنيو",
        emoji="إيموجي للرول (اختياري)",
        description="وصف قصير للرول (اختياري)",
    )
    async def addrole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        label: str,
        emoji: str = None,
        description: str = None,
    ):
        settings = _settings()
        roles_config = settings.get("roles", [])

        if len(roles_config) >= 25 and not any(r["role_id"] == role.id for r in roles_config):
            await interaction.response.send_message(
                "❌ المنيو وصلات للحد الأقصى (25 رول). حيد واحد قبل ما تزيد آخر.",
                ephemeral=True,
            )
            return

        roles_config = [r for r in roles_config if r["role_id"] != role.id]
        roles_config.append({
            "role_id": role.id,
            "label": label,
            "emoji": emoji,
            "description": description,
        })
        settings["roles"] = roles_config
        _save_settings(settings)

        await interaction.response.send_message(
            embed=discord.Embed(
                description=(
                    f"✅ تزاد {role.mention} لمنيو الاختيار باسم **{label}**.\n"
                    "استخدم `/rolepicker setup` باش ترفريش البانيل."
                ),
                color=config.SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    @rolepicker_group.command(name="removerole", description="➖ حيد رول من منيو الاختيار")
    @app_commands.describe(role="الرول لي بغيتي تحيدو")
    async def removerole(self, interaction: discord.Interaction, role: discord.Role):
        settings = _settings()
        roles_config = settings.get("roles", [])
        new_config = [r for r in roles_config if r["role_id"] != role.id]

        if len(new_config) == len(roles_config):
            await interaction.response.send_message(f"❌ {role.mention} ماشي مزاد للمنيو.", ephemeral=True)
            return

        settings["roles"] = new_config
        _save_settings(settings)
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"🗑️ تحيد {role.mention} من المنيو. استخدم `/rolepicker setup` باش ترفريش البانيل.",
                color=config.SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    @rolepicker_group.command(name="list", description="📋 شوف الرولات المزادة للمنيو")
    async def list_roles(self, interaction: discord.Interaction):
        settings = _settings()
        roles_config = settings.get("roles", [])
        if not roles_config:
            await interaction.response.send_message("❌ ماكاين حتى رول مزاد بعد.", ephemeral=True)
            return

        lines = []
        for r in roles_config:
            role = interaction.guild.get_role(r["role_id"])
            mention = role.mention if role else f"<#{r['role_id']}> (محذوف)"
            lines.append(f"• **{r['label']}** — {mention}")

        await interaction.response.send_message(
            embed=discord.Embed(
                title="📋 رولات منيو الاختيار",
                description="\n".join(lines),
                color=config.EMBED_COLOR,
            ),
            ephemeral=True,
        )

    @rolepicker_group.command(name="setup", description="🖱️ بعث/رفريش بانيل اختيار الرولات فـ روم")
    @app_commands.describe(channel="الروم لي غادي يتبعت فيها البانيل")
    async def setup_panel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        settings = _settings()
        if not settings.get("roles"):
            await interaction.response.send_message(
                "❌ زيد أولاً شي رول بـ `/rolepicker addrole`.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🎭 اختار الرولات ديالك",
            description="استخدم المنيو تحت باش تختار الرولات لي بغيتي — تقدر تبدل الاختيار فأي وقت.",
            color=config.EMBED_COLOR,
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

        await channel.send(embed=embed, view=RolePickerView())

        settings["panel_channel_id"] = channel.id
        _save_settings(settings)

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ تم بعث بانيل اختيار الرولات فـ {channel.mention}.",
                color=config.SUCCESS_COLOR,
            ),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(RolePicker(bot))
