"""
Subscribe Approval System — Ghostx Community
─────────────────────────────────────────────
Same idea as the Boost system, running side by side with its own channel,
role and settings so a server can run both at once.
• Admin runs /subscribe setup — channel, role, reviewer role, mode and emoji
  are picked directly from Discord's native pickers.
• /subscribe update    — change only the fields you pass, everything else stays as is.
• /subscribe remove    — disable the system.
• /subscribe info      — show current settings.
• /subscribe customize — change the review panel's title/description/button text & emoji.
• When a user posts an image in the watch channel:
    - Mode "react": bot reacts with the chosen emoji. If a reviewer also reacts, user gets the subscriber role.
    - Mode "panel": bot posts a short text review card below the image with Accept/Reject buttons.
• Only members with the configured reviewer role (or Manage Roles if none is set)
  can Accept/Reject or approve via reaction.

All responses are plain text (no embeds) — short and to the point.
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import db
from datetime import datetime

from cogs import panel_settings
from cogs import emoji_loader

SUBSCRIBE_COLLECTION = "subscribe_settings"

# ─── custom emojis (uploaded by ghostx_1x on the FastLife/Ghostx server) ───
EMOJI = {
    "accept": "<:fl_check:1528968902837538846>",
    "reject": "<:fl_x:1528968940749848636>",
    "proof": "<:verified:1530120198080827583>",
    "success": "<:squarecheckmark:1530119784878964786>",
    "error": "<:x:1530119812515106928>",
    "warning": "<:warning:1530119891326079118>",
    "role": "<:roleids:1530119978773381192>",
    "settings": "<:settings:1530119866366034010>",
    "info": "<:info:1530120094363942963>",
    "remove": "<:supprimer:1530119918660354139>",
}


def load_subscribe() -> dict:
    return db.load(SUBSCRIBE_COLLECTION)


def save_subscribe(data: dict):
    db.save(SUBSCRIBE_COLLECTION, data)


def _msg(emoji: str, title: str, **fields) -> str:
    """Consistent short plain-text layout: emoji + bold title, then fields."""
    lines = [f"{emoji} **{title}**"]
    for label, value in fields.items():
        if value is not None:
            lines.append(f"› **{label}:** {value}")
    return "\n".join(lines)


def _can_review(member: discord.Member, reviewer_role_id: int | None) -> bool:
    """Only the configured reviewer role can Accept/Reject — falls back to Manage Roles if none is set."""
    if reviewer_role_id:
        role = member.guild.get_role(reviewer_role_id)
        if role:
            return role in member.roles
    return member.guild_permissions.manage_roles


# ─── Accept / Reject panel view ─────────────────────────────────────────────
class SubscribeReviewPanel(discord.ui.View):
    def __init__(self, target_user_id: int, guild_id: int, subscriber_role_id: int, reviewer_role_id: int = None):
        super().__init__(timeout=None)
        self.target_user_id     = target_user_id
        self.guild_id           = guild_id
        self.subscriber_role_id = subscriber_role_id
        self.reviewer_role_id   = reviewer_role_id

        accept_emoji = emoji_loader.get_obj("fl_check") or panel_settings.get("subscribe_accept_emoji") or EMOJI["accept"]
        reject_emoji = emoji_loader.get_obj("fl_x")     or panel_settings.get("subscribe_reject_emoji") or EMOJI["reject"]

        accept_btn = discord.ui.Button(
            label=panel_settings.get("subscribe_accept_label") or "Accept",
            emoji=accept_emoji,
            style=discord.ButtonStyle.success,
            custom_id="subscribe_accept",
        )
        reject_btn = discord.ui.Button(
            label=panel_settings.get("subscribe_reject_label") or "Reject",
            emoji=reject_emoji,
            style=discord.ButtonStyle.danger,
            custom_id="subscribe_reject",
        )
        accept_btn.callback = self.accept
        reject_btn.callback = self.reject
        self.add_item(accept_btn)
        self.add_item(reject_btn)

    async def accept(self, interaction: discord.Interaction):
        if not _can_review(interaction.user, self.reviewer_role_id):
            await interaction.response.send_message(f"{EMOJI['error']} You're not allowed to review proofs.", ephemeral=True)
            return

        guild  = interaction.guild
        member = guild.get_member(self.target_user_id)
        role   = guild.get_role(self.subscriber_role_id) if self.subscriber_role_id else None

        if not member:
            await interaction.response.send_message(f"{EMOJI['error']} Member not found (they may have left).", ephemeral=True)
            return

        try:
            if role:
                await member.add_roles(role, reason="Subscribe approved by admin")
            await interaction.response.edit_message(
                content=_msg(
                    EMOJI["success"], "Subscribe Approved",
                    User=member.mention,
                    Role=role.mention if role else "subscriber role",
                    Moderator=interaction.user.mention,
                ),
                view=None,
            )
        except Exception as e:
            await interaction.response.send_message(f"{EMOJI['error']} Error: {e}", ephemeral=True)

    async def reject(self, interaction: discord.Interaction):
        if not _can_review(interaction.user, self.reviewer_role_id):
            await interaction.response.send_message(f"{EMOJI['error']} You're not allowed to review proofs.", ephemeral=True)
            return

        guild  = interaction.guild
        member = guild.get_member(self.target_user_id)

        await interaction.response.edit_message(
            content=_msg(
                EMOJI["reject"], "Subscribe Rejected",
                User=member.mention if member else "Unknown",
                Moderator=interaction.user.mention,
            ),
            view=None,
        )


# ─── Subscribe Cog ───────────────────────────────────────────────────────────
class Subscribe(commands.Cog):
    subscribe_group = app_commands.Group(
        name="subscribe",
        description="🔔 Manage the subscribe approval system",
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

        ss = load_subscribe()
        cfg = ss.get(str(message.guild.id))
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
        subscriber_role_id = cfg.get("subscriber_role_id")
        reviewer_role_id = cfg.get("reviewer_role_id")

        if mode == "react":
            emoji = cfg.get("reaction_emoji") or "✅"
            try:
                await message.add_reaction(emoji)
            except Exception:
                pass

        else:  # panel mode — short text card under the image the user already posted
            view = SubscribeReviewPanel(
                target_user_id=message.author.id,
                guild_id=message.guild.id,
                subscriber_role_id=subscriber_role_id or 0,
                reviewer_role_id=reviewer_role_id,
            )
            await message.reply(
                _msg(EMOJI["proof"], "Subscribe Proof", User=message.author.mention, Status="Waiting for review"),
                view=view,
                mention_author=False,
            )

    # ── React listener: if a reviewer reacts with the chosen emoji → give role ──
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

        ss = load_subscribe()
        cfg = ss.get(str(guild.id))
        if not cfg or not cfg.get("enabled"):
            return
        if cfg.get("mode") != "react":
            return
        if not _can_review(member, cfg.get("reviewer_role_id")):
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

        subscriber_role_id = cfg.get("subscriber_role_id")
        role = guild.get_role(subscriber_role_id) if subscriber_role_id else None
        target = msg.author if isinstance(msg.author, discord.Member) else guild.get_member(msg.author.id)
        if not target or not role:
            return

        try:
            await target.add_roles(role, reason="Subscribe approved via reaction")
            await channel.send(
                _msg(EMOJI["success"], "Subscribe Approved", User=target.mention, Role=role.mention),
                delete_after=10
            )
        except Exception:
            pass

    # ─── /subscribe setup ────────────────────────────────────────────────────
    @subscribe_group.command(name="setup", description="⚙️ Set up the subscribe approval system")
    @app_commands.describe(
        channel="Channel where members post their subscribe proof images",
        role="Role to give when a subscribe is approved",
        mode="panel = Accept/Reject buttons | react = emoji reaction",
        emoji="Emoji to react with — only used in react mode (default ✅)",
        reviewer_role="Only members with this role can Accept/Reject (optional — defaults to Manage Roles)",
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="panel — Accept/Reject buttons", value="panel"),
        app_commands.Choice(name="react — emoji reaction", value="react"),
    ])
    async def subscribe_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        role: discord.Role,
        mode: str = "panel",
        emoji: str = "✅",
        reviewer_role: discord.Role = None,
    ):
        cfg = {
            "enabled": True,
            "watch_channel_id": channel.id,
            "subscriber_role_id": role.id,
            "mode": mode,
            "reaction_emoji": emoji or "✅",
            "reviewer_role_id": reviewer_role.id if reviewer_role else None,
        }
        ss = load_subscribe()
        ss[str(interaction.guild_id)] = cfg
        save_subscribe(ss)
        await interaction.response.send_message(
            self._summary(EMOJI["success"], "Subscribe System Set Up", channel, role, mode, cfg["reaction_emoji"], reviewer_role),
            ephemeral=True
        )

    # ─── /subscribe update ───────────────────────────────────────────────────
    @subscribe_group.command(name="update", description="✏️ Update the subscribe system — only fill in what you want to change")
    @app_commands.describe(
        channel="New watch channel (optional)",
        role="New subscriber role (optional)",
        mode="New mode (optional)",
        emoji="New reaction emoji — react mode only (optional)",
        reviewer_role="New reviewer role — send the @everyone role to clear it (optional)",
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="panel — Accept/Reject buttons", value="panel"),
        app_commands.Choice(name="react — emoji reaction", value="react"),
    ])
    async def subscribe_update(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
        role: discord.Role = None,
        mode: str = None,
        emoji: str = None,
        reviewer_role: discord.Role = None,
    ):
        ss = load_subscribe()
        guild_id = str(interaction.guild_id)
        cfg = ss.get(guild_id)
        if not cfg:
            await interaction.response.send_message(f"{EMOJI['error']} Subscribe system not set up yet. Use `/subscribe setup` first.", ephemeral=True)
            return

        if channel: cfg["watch_channel_id"] = channel.id
        if role:    cfg["subscriber_role_id"] = role.id
        if mode:    cfg["mode"] = mode
        if emoji:   cfg["reaction_emoji"] = emoji
        if reviewer_role:
            cfg["reviewer_role_id"] = None if reviewer_role.is_default() else reviewer_role.id
        cfg["enabled"] = True

        ss[guild_id] = cfg
        save_subscribe(ss)

        ch  = interaction.guild.get_channel(cfg["watch_channel_id"])
        rl  = interaction.guild.get_role(cfg["subscriber_role_id"])
        rv  = interaction.guild.get_role(cfg["reviewer_role_id"]) if cfg.get("reviewer_role_id") else None
        await interaction.response.send_message(
            self._summary(EMOJI["success"], "Subscribe Settings Updated", ch, rl, cfg.get("mode", "panel"), cfg.get("reaction_emoji", "✅"), rv),
            ephemeral=True
        )

    # ─── /subscribe remove ───────────────────────────────────────────────────
    @subscribe_group.command(name="remove", description="🗑️ Disable the subscribe approval system")
    async def subscribe_remove(self, interaction: discord.Interaction):
        ss = load_subscribe()
        ss.pop(str(interaction.guild_id), None)
        save_subscribe(ss)
        await interaction.response.send_message(
            _msg(EMOJI["remove"], "Subscribe System Removed", Status="Disabled"),
            ephemeral=True
        )

    # ─── /subscribe info ─────────────────────────────────────────────────────
    @subscribe_group.command(name="info", description="📊 Show current subscribe system settings")
    async def subscribe_info(self, interaction: discord.Interaction):
        ss = load_subscribe()
        cfg = ss.get(str(interaction.guild_id))
        if not cfg:
            await interaction.response.send_message(f"{EMOJI['info']} Subscribe system is not set up yet.", ephemeral=True)
            return
        ch = interaction.guild.get_channel(cfg.get("watch_channel_id") or 0)
        rl = interaction.guild.get_role(cfg.get("subscriber_role_id") or 0)
        rv = interaction.guild.get_role(cfg.get("reviewer_role_id") or 0) if cfg.get("reviewer_role_id") else None
        await interaction.response.send_message(
            self._summary(EMOJI["info"], "Subscribe System Settings", ch, rl, cfg.get("mode", "panel"), cfg.get("reaction_emoji", "✅"), rv),
            ephemeral=True
        )

    # ─── /subscribe customize ────────────────────────────────────────────────
    @subscribe_group.command(name="customize", description="🎨 Customize the subscribe review card's text and buttons")
    @app_commands.describe(
        title="Review card title (optional)",
        description="Review card status text (optional)",
        accept_label="Accept button label (optional)",
        accept_emoji="Accept button emoji (optional)",
        reject_label="Reject button label (optional)",
        reject_emoji="Reject button emoji (optional)",
    )
    async def subscribe_customize(
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
            await interaction.response.send_message(f"{EMOJI['error']} Provide at least one field to change.", ephemeral=True)
            return
        panel_settings.set_values(
            subscribe_title=title,
            subscribe_description=description,
            subscribe_accept_label=accept_label,
            subscribe_accept_emoji=accept_emoji,
            subscribe_reject_label=reject_label,
            subscribe_reject_emoji=reject_emoji,
        )
        await interaction.response.send_message(
            _msg(EMOJI["success"], "Subscribe Card Customized", Status="Applies to the next proof posted"),
            ephemeral=True
        )

    # ─── helper ─────────────────────────────────────────────────────────────
    def _summary(self, emoji, title, channel, role, mode, reaction_emoji, reviewer_role) -> str:
        fields = {
            "Watch Channel": channel.mention if channel else "Not set",
            "Subscriber Role": role.mention if role else "Not set",
            "Reviewer Role": reviewer_role.mention if reviewer_role else "Anyone with Manage Roles",
            "Mode": f"`{mode}`",
        }
        if mode == "react":
            fields["Reaction Emoji"] = reaction_emoji
        return _msg(emoji, title, **fields)


async def setup(bot):
    await bot.add_cog(Subscribe(bot))
