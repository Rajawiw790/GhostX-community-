"""
Boost Approval System
─────────────────────
• Admin runs /boost setup — channel, role, mode and emoji are picked directly
  from Discord's native pickers (no more typing IDs by hand).
• /boost update  — change only the fields you pass, everything else stays as is.
• /boost remove  — disable the system.
• /boost info    — show current settings.
• /boost customize — change the review panel's title/description/button text & emoji.
• When a user posts an image in the watch channel:
    - Mode "react": bot reacts with the chosen emoji. If admin also reacts, user gets the booster role.
    - Mode "panel": bot posts a review card below the image with Accept/Reject buttons
      (styled like a proof-submission ticket: "User: @member" + status text + the image as proof).
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import db
from datetime import datetime

from cogs import panel_settings
from cogs import emoji_loader

BOOST_COLLECTION = "boost_settings"


def load_boost() -> dict:
    return db.load(BOOST_COLLECTION)


def save_boost(data: dict):
    db.save(BOOST_COLLECTION, data)


# ─── Accept / Reject panel view ─────────────────────────────────────────────
class BoostReviewPanel(discord.ui.View):
    def __init__(self, target_user_id: int, guild_id: int, booster_role_id: int):
        super().__init__(timeout=None)
        self.target_user_id  = target_user_id
        self.guild_id        = guild_id
        self.booster_role_id = booster_role_id

        accept_emoji = emoji_loader.get_obj("fl_check") or panel_settings.get("boost_accept_emoji") or "✅"
        reject_emoji = emoji_loader.get_obj("fl_x")     or panel_settings.get("boost_reject_emoji") or "❌"

        accept_btn = discord.ui.Button(
            label=panel_settings.get("boost_accept_label") or "Accept",
            emoji=accept_emoji,
            style=discord.ButtonStyle.success,
            custom_id="boost_accept",
        )
        reject_btn = discord.ui.Button(
            label=panel_settings.get("boost_reject_label") or "Reject",
            emoji=reject_emoji,
            style=discord.ButtonStyle.danger,
            custom_id="boost_reject",
        )
        accept_btn.callback = self.accept
        reject_btn.callback = self.reject
        self.add_item(accept_btn)
        self.add_item(reject_btn)

    async def accept(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ You don't have permission to manage roles.", ephemeral=True)
            return

        guild  = interaction.guild
        member = guild.get_member(self.target_user_id)
        role   = guild.get_role(self.booster_role_id) if self.booster_role_id else None

        if not member:
            await interaction.response.send_message("❌ Member not found (they may have left).", ephemeral=True)
            return

        try:
            if role:
                await member.add_roles(role, reason="Boost approved by admin")
            embed = discord.Embed(
                title="✅ Boost Approved",
                description=f"**User:** {member.mention}\n\nApproved — they now have {role.mention if role else 'the booster role'}.",
                color=config.SUCCESS_COLOR,
                timestamp=datetime.now()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=panel_settings.render(panel_settings.get("boost_footer")) or f"Approved by {interaction.user.display_name} | {config.BOT_NAME}")
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    async def reject(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
            return

        guild  = interaction.guild
        member = guild.get_member(self.target_user_id)

        embed = discord.Embed(
            title="❌ Boost Rejected",
            description=f"**User:** {member.mention if member else 'Unknown'}\n\nRejected by {interaction.user.mention}.",
            color=config.ERROR_COLOR,
            timestamp=datetime.now()
        )
        embed.set_footer(text=panel_settings.render(panel_settings.get("boost_footer")) or f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.edit_message(embed=embed, view=None)


# ─── Boost Cog ───────────────────────────────────────────────────────────────
class Boost(commands.Cog):
    boost_group = app_commands.Group(
        name="boost",
        description="🌟 Manage the boost approval system",
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(self, bot):
        self.bot = bot

    # ── Watch for images in the configured channel ─────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return

        bs = load_boost()
        cfg = bs.get(str(message.guild.id))
        if not cfg or not cfg.get("enabled"):
            return

        watch_ch_id = cfg.get("watch_channel_id")
        if not watch_ch_id or message.channel.id != watch_ch_id:
            return

        # Only trigger on messages with images
        image_attachment = next(
            (a for a in message.attachments if a.content_type and a.content_type.startswith("image/")),
            None
        )
        if not image_attachment:
            return

        mode = cfg.get("mode", "panel")
        booster_role_id = cfg.get("booster_role_id")

        if mode == "react":
            emoji = cfg.get("reaction_emoji") or "✅"
            try:
                await message.add_reaction(emoji)
            except Exception:
                pass

        else:  # panel mode — styled as a "proof" review card
            title = panel_settings.render(panel_settings.get("boost_title")) or "🌟 Boost Proof"
            description = panel_settings.render(panel_settings.get("boost_description")) or (
                "Your proof has been submitted. Please wait for review."
            )
            embed = discord.Embed(
                title=title,
                description=f"**User:** {message.author.mention}\n\n{description}",
                color=config.EMBED_COLOR,
                timestamp=datetime.now()
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)
            embed.set_image(url=image_attachment.url)
            embed.set_footer(text=panel_settings.render(panel_settings.get("boost_footer")) or f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

            view = BoostReviewPanel(
                target_user_id=message.author.id,
                guild_id=message.guild.id,
                booster_role_id=booster_role_id or 0
            )
            await message.channel.send(embed=embed, view=view)

    # ── React listener: if admin reacts with the chosen emoji → give role ──
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return
        if not member.guild_permissions.manage_roles:
            return

        bs = load_boost()
        cfg = bs.get(str(guild.id))
        if not cfg or not cfg.get("enabled"):
            return
        if cfg.get("mode") != "react":
            return

        watch_ch_id = cfg.get("watch_channel_id")
        if payload.channel_id != watch_ch_id:
            return

        reaction_emoji = cfg.get("reaction_emoji") or "✅"
        if str(payload.emoji) != reaction_emoji:
            return

        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return

        try:
            msg = await channel.fetch_message(payload.message_id)
        except Exception:
            return

        if msg.author.bot:
            return

        booster_role_id = cfg.get("booster_role_id")
        role = guild.get_role(booster_role_id) if booster_role_id else None
        target = msg.author if isinstance(msg.author, discord.Member) else guild.get_member(msg.author.id)
        if not target or not role:
            return

        try:
            await target.add_roles(role, reason="Boost approved via reaction")
            await channel.send(
                embed=discord.Embed(
                    title="✅ Boost Approved",
                    description=f"{target.mention} has been given {role.mention}!",
                    color=config.SUCCESS_COLOR
                ),
                delete_after=10
            )
        except Exception:
            pass

    # ─── /boost setup ───────────────────────────────────────────────────────
    @boost_group.command(name="setup", description="⚙️ Set up the boost approval system")
    @app_commands.describe(
        channel="Channel where members post their boost proof images",
        role="Role to give when a boost is approved",
        mode="panel = Accept/Reject buttons | react = emoji reaction",
        emoji="Emoji to react with — only used in react mode (default ✅)"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="panel — Accept/Reject buttons", value="panel"),
        app_commands.Choice(name="react — emoji reaction", value="react"),
    ])
    async def boost_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        role: discord.Role,
        mode: str = "panel",
        emoji: str = "✅",
    ):
        cfg = {
            "enabled": True,
            "watch_channel_id": channel.id,
            "booster_role_id": role.id,
            "mode": mode,
            "reaction_emoji": emoji or "✅",
        }
        bs = load_boost()
        bs[str(interaction.guild_id)] = cfg
        save_boost(bs)
        await interaction.response.send_message(embed=self._summary_embed("✅ Boost System Set Up!", channel, role, mode, cfg["reaction_emoji"]), ephemeral=True)

    # ─── /boost update ──────────────────────────────────────────────────────
    @boost_group.command(name="update", description="✏️ Update the boost system — only fill in what you want to change")
    @app_commands.describe(
        channel="New watch channel (optional)",
        role="New booster role (optional)",
        mode="New mode (optional)",
        emoji="New reaction emoji — react mode only (optional)"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="panel — Accept/Reject buttons", value="panel"),
        app_commands.Choice(name="react — emoji reaction", value="react"),
    ])
    async def boost_update(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
        role: discord.Role = None,
        mode: str = None,
        emoji: str = None,
    ):
        bs = load_boost()
        guild_id = str(interaction.guild_id)
        cfg = bs.get(guild_id)
        if not cfg:
            await interaction.response.send_message("❌ Boost system not set up yet. Use `/boost setup` first.", ephemeral=True)
            return

        if channel: cfg["watch_channel_id"] = channel.id
        if role:    cfg["booster_role_id"] = role.id
        if mode:    cfg["mode"] = mode
        if emoji:   cfg["reaction_emoji"] = emoji
        cfg["enabled"] = True

        bs[guild_id] = cfg
        save_boost(bs)

        ch  = interaction.guild.get_channel(cfg["watch_channel_id"])
        rl  = interaction.guild.get_role(cfg["booster_role_id"])
        await interaction.response.send_message(
            embed=self._summary_embed("✅ Boost Settings Updated!", ch, rl, cfg.get("mode", "panel"), cfg.get("reaction_emoji", "✅")),
            ephemeral=True
        )

    # ─── /boost remove ──────────────────────────────────────────────────────
    @boost_group.command(name="remove", description="🗑️ Disable the boost approval system")
    async def boost_remove(self, interaction: discord.Interaction):
        bs = load_boost()
        bs.pop(str(interaction.guild_id), None)
        save_boost(bs)
        embed = discord.Embed(
            title="🗑️ Boost System Removed",
            description="The boost approval system has been disabled.",
            color=config.ERROR_COLOR
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─── /boost info ────────────────────────────────────────────────────────
    @boost_group.command(name="info", description="📊 Show current boost system settings")
    async def boost_info(self, interaction: discord.Interaction):
        bs = load_boost()
        cfg = bs.get(str(interaction.guild_id))
        if not cfg:
            await interaction.response.send_message("ℹ️ Boost system is not set up yet.", ephemeral=True)
            return
        ch = interaction.guild.get_channel(cfg.get("watch_channel_id") or 0)
        rl = interaction.guild.get_role(cfg.get("booster_role_id") or 0)
        await interaction.response.send_message(
            embed=self._summary_embed("📊 Boost System Settings", ch, rl, cfg.get("mode", "panel"), cfg.get("reaction_emoji", "✅")),
            ephemeral=True
        )

    # ─── /boost customize ───────────────────────────────────────────────────
    @boost_group.command(name="customize", description="🎨 Customize the boost review card's text and buttons")
    @app_commands.describe(
        title="Review card title (optional)",
        description="Review card status text (optional)",
        accept_label="Accept button label (optional)",
        accept_emoji="Accept button emoji (optional)",
        reject_label="Reject button label (optional)",
        reject_emoji="Reject button emoji (optional)",
    )
    async def boost_customize(
        self,
        interaction: discord.Interaction,
        title: str = None,
        description: str = None,
        accept_label: str = None,
        accept_emoji: str = None,
        reject_label: str = None,
        reject_emoji: str = None,
    ):
        if not any([title, description, accept_label, accept_emoji, reject_label, reject_emoji]):
            await interaction.response.send_message("❌ Provide at least one field to change.", ephemeral=True)
            return
        panel_settings.set_values(
            boost_title=title,
            boost_description=description,
            boost_accept_label=accept_label,
            boost_accept_emoji=accept_emoji,
            boost_reject_label=reject_label,
            boost_reject_emoji=reject_emoji,
        )
        embed = discord.Embed(
            title="✅ Boost Card Customized",
            description="Changes will apply to the next boost proof posted.",
            color=config.SUCCESS_COLOR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─── helper ─────────────────────────────────────────────────────────────
    def _summary_embed(self, title, channel, role, mode, emoji) -> discord.Embed:
        embed = discord.Embed(title=title, color=config.SUCCESS_COLOR)
        embed.add_field(name="📢 Watch Channel", value=channel.mention if channel else "❌ Not set", inline=True)
        embed.add_field(name="🏷️ Booster Role",  value=role.mention if role else "❌ Not set", inline=True)
        embed.add_field(name="⚙️ Mode",           value=f"`{mode}`", inline=True)
        if mode == "react":
            embed.add_field(name="😀 Reaction Emoji", value=emoji, inline=True)
        embed.add_field(
            name="ℹ️ How it works",
            value=(
                "When a member posts an image in the watch channel:\n"
                + ("• Bot reacts with the emoji. Admin reacts too → member gets the role." if mode == "react"
                   else "• Bot shows a review card with Accept/Reject buttons. Admin clicks Accept → member gets the role.")
            ),
            inline=False
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        return embed


async def setup(bot):
    await bot.add_cog(Boost(bot))
