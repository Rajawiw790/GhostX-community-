import discord
from discord.ext import commands
from discord import app_commands
import config
import settings
from cogs import emoji_loader
from cogs import panel_settings


class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        verify_emoji = emoji_loader.get_obj("fl_verify") or panel_settings.get("verify_button_emoji")

        btn = discord.ui.Button(
            label=panel_settings.get("verify_button_label") or "Verify",
            style=discord.ButtonStyle.success,
            custom_id="verify_btn",
            emoji=verify_emoji,
        )
        btn.callback = self.verify_button
        self.add_item(btn)

    async def verify_button(self, interaction: discord.Interaction):
        e_check    = emoji_loader.get("fl_check")    or "✅"
        e_x        = emoji_loader.get("fl_x")        or "❌"
        e_warning  = emoji_loader.get("fl_warning")  or "⚠️"
        e_verified = emoji_loader.get("fl_verified") or "✅"

        role = interaction.guild.get_role(config.VERIFIED_ROLE_ID)
        if not role:
            embed = discord.Embed(
                description=f"{e_x} Verified role not found! Please contact an administrator.",
                color=config.ERROR_COLOR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if role in interaction.user.roles:
            embed = discord.Embed(
                description=f"{e_warning} You are already verified!",
                color=config.WARNING_COLOR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        try:
            await interaction.user.add_roles(role)
            embed = discord.Embed(
                title=f"{e_verified} Verified Successfully!",
                description=(
                    f"**Welcome {interaction.user.mention}!** 🎉\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{e_check} You can now access all channels\n"
                    f"{e_check} Enjoy your time in **{config.SERVER_NAME}**!\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=config.SUCCESS_COLOR
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            embed.set_footer(
                text=panel_settings.render(panel_settings.get("verify_footer")) or f"{config.BOT_NAME} | Dev: {config.DEVELOPER}"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"{e_x} I don't have permission to assign that role!\nMake sure my role is above the verified role.",
                    color=config.ERROR_COLOR
                ),
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"{e_x} An error occurred: {e}",
                    color=config.ERROR_COLOR
                ),
                ephemeral=True
            )


class Verify(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="verify-setup", description="✅ Set up the verification system")
    @app_commands.describe(
        channel="The channel to post the verification panel in",
        verified_role="Role given to verified members",
        banner_url="Banner image URL (optional)",
        description="Custom description (optional)"
    )
    @app_commands.default_permissions(administrator=True)
    async def verify_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        verified_role: discord.Role,
        banner_url: str = None,
        description: str = None
    ):
        config.VERIFY_CHANNEL_ID = channel.id
        config.VERIFIED_ROLE_ID  = verified_role.id
        if banner_url:
            settings.set("verify_banner_url", banner_url)

        custom_desc = description or panel_settings.render(panel_settings.get("verify_description")) or (
            "Click the button below to verify yourself and gain access to the server."
        )

        embed = discord.Embed(
            title=panel_settings.render(panel_settings.get("verify_title")) or f"## 👋 Welcome!\n\n{custom_desc}\n\n━━━━━━━━━━━━━━━━━━━━━━━━",
            description=custom_desc,
            color=config.EMBED_COLOR
        )
        embed.set_footer(
            text=panel_settings.render(panel_settings.get("verify_footer")) or f"{config.BOT_NAME} | Dev: {config.DEVELOPER}"
        )

        stored_banner = banner_url or settings.get("verify_banner_url")
        if stored_banner:
            embed.set_image(url=stored_banner)

        await channel.send(embed=embed, view=VerifyView())

        confirm = discord.Embed(
            title="✅ Verification System Set Up!",
            description=(
                f"📢 Channel: {channel.mention}\n"
                f"🏷️ Role: {verified_role.mention}"
            ),
            color=config.SUCCESS_COLOR
        )
        confirm.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=confirm, ephemeral=True)

    @app_commands.command(name="verify-banner", description="🖼️ Change the verification banner image")
    @app_commands.describe(url="The new banner image URL")
    @app_commands.default_permissions(administrator=True)
    async def verify_banner(self, interaction: discord.Interaction, url: str):
        settings.set("verify_banner_url", url)
        embed = discord.Embed(title="🖼️ Verification Banner Updated", color=config.SUCCESS_COLOR)
        embed.set_image(url=url)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="verify-customize", description="🛠️ Customize the verification panel title/content/footer")
    @app_commands.describe(
        title="Panel title (optional)",
        description="Panel content (optional)",
        footer="Panel footer (optional)"
    )
    @app_commands.default_permissions(administrator=True)
    async def verify_customize(
        self,
        interaction: discord.Interaction,
        title: str = None,
        description: str = None,
        footer: str = None
    ):
        panel_settings.set_values(verify_title=title, verify_description=description, verify_footer=footer)
        embed = discord.Embed(
            title="✅ Verification Panel Updated",
            description="Changes will apply the next time you run `/verify-setup`.",
            color=config.SUCCESS_COLOR,
        )
        if title:
            embed.add_field(name="📌 Title", value=title, inline=False)
        if description:
            embed.add_field(name="📝 Content", value=description[:1000], inline=False)
        if footer:
            embed.add_field(name="🔻 Footer", value=footer, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="verify-buttons-customize", description="🔘 Customize the verify button text and emoji")
    @app_commands.describe(
        label="New button label (optional)",
        emoji="New button emoji (optional, e.g. ✅ or <:name:id>)",
    )
    @app_commands.default_permissions(administrator=True)
    async def verify_buttons_customize(
        self,
        interaction: discord.Interaction,
        label: str = None,
        emoji: str = None,
    ):
        if not label and not emoji:
            await interaction.response.send_message("❌ Please provide at least a new label or emoji!", ephemeral=True)
            return
        panel_settings.set_values(verify_button_label=label, verify_button_emoji=emoji)
        embed = discord.Embed(
            title="✅ Verify Button Updated",
            description="Changes will apply the next time you run `/verify-setup`.",
            color=config.SUCCESS_COLOR,
        )
        if label:
            embed.add_field(name="Label", value=label, inline=True)
        if emoji:
            embed.add_field(name="Emoji", value=emoji, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Verify(bot))
