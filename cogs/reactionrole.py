"""
Reaction Role System — Ghostx Community
────────────────────────────────────────
/reactionrole add     – link emoji + role to any message (role & channel are
                         native Discord pickers — no typing IDs by hand)
/reactionrole remove  – remove one emoji pair from a message (autocomplete
                         dropdowns for both the message and the emoji — no IDs)
/reactionrole list    – show all setups in this server
/reactionrole clear   – remove every reaction role from a message (autocomplete)

Right-click any message → Apps → "➕ Add Reaction Role" for the fastest,
fully no-typing flow: pick the emoji in a one-field modal, then pick the role
from a native role-select dropdown. No message link, no channel ID, no role ID.

Pattern used:
  • app_commands.Group defined as a CLASS ATTRIBUTE of the Cog
    → discord.py binds 'self' (the Cog instance) properly
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import db

RR_COLLECTION = "reaction_roles"


# ─── Storage ──────────────────────────────────────────────────────────────────

def load_rr() -> dict:
    return db.load(RR_COLLECTION)


def save_rr(data: dict):
    db.save(RR_COLLECTION, data)


def rr_key(guild_id: int, channel_id: int, message_id: int) -> str:
    return f"{guild_id}:{channel_id}:{message_id}"


def parse_link(value: str):
    """Return (channel_id, message_id) or (None, None)."""
    value = value.strip()
    if "discord.com/channels/" in value:
        parts = value.rstrip("/").split("/")
        try:
            return int(parts[-2]), int(parts[-1])
        except (ValueError, IndexError):
            return None, None
    try:
        return None, int(value)
    except ValueError:
        return None, None


def _guild_entries(guild_id: int) -> dict:
    rr = load_rr()
    prefix = f"{guild_id}:"
    return {k: v for k, v in rr.items() if k.startswith(prefix)}


# ─── Right-click flow: no typing at all except the emoji ──────────────────────

class RRRolePickView(discord.ui.View):
    """Shown after the emoji modal — a native role-select dropdown."""

    def __init__(self, message: discord.Message, emoji_str: str):
        super().__init__(timeout=120)
        self.message = message
        self.emoji_str = emoji_str

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Pick the role to link…")
    async def pick_role(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        role = select.values[0]

        rr = load_rr()
        key = rr_key(self.message.guild.id, self.message.channel.id, self.message.id)
        rr.setdefault(key, {"pairs": {}})["pairs"][self.emoji_str] = role.id
        save_rr(rr)

        embed = discord.Embed(title="✅ Reaction Role Added!", color=config.SUCCESS_COLOR)
        embed.add_field(name="📌 Message", value=f"[Jump]({self.message.jump_url})", inline=True)
        embed.add_field(name="Emoji", value=self.emoji_str, inline=True)
        embed.add_field(name="Role", value=role.mention, inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Reacting gives {role.name}")

        self.stop()
        await interaction.response.edit_message(content=None, embed=embed, view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class RRQuickEmojiModal(discord.ui.Modal, title="🎭 Add Reaction Role"):
    """The only text field left in the whole flow — Discord has no bot-facing
    emoji picker, so this one is unavoidable."""

    emoji_field = discord.ui.TextInput(
        label="Emoji",
        placeholder="e.g.  ✅   or   👍   or   <:custom:123456789>",
        required=True,
        max_length=60,
    )

    def __init__(self, message: discord.Message):
        super().__init__()
        self.message = message

    async def on_submit(self, interaction: discord.Interaction):
        emoji_str = self.emoji_field.value.strip()
        try:
            await self.message.add_reaction(emoji_str)
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"❌ Couldn't react with `{emoji_str}` — make sure the emoji is valid.\n`{e}`",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Reacted with {emoji_str} — now pick the role to link it to:",
            view=RRRolePickView(self.message, emoji_str),
            ephemeral=True,
        )


# ─── Cog with Group as class attribute (discord.py recommended pattern) ───────

class ReactionRole(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    rr = app_commands.Group(
        name="reactionrole",
        description="Manage reaction roles",
        default_permissions=discord.Permissions(manage_roles=True),
    )

    pass  # context menu registered at module level below

    # ── /reactionrole add — role & channel are real pickers, only the
    #    message link/ID stays as text (Discord has no "pick a message"
    #    slash-command option type; use the right-click flow above to skip it) ──
    @rr.command(name="add", description="Link an emoji + role to a message (or right-click the message → Apps)")
    @app_commands.describe(
        message_link="Message link (right-click the message → Copy Message Link) or a plain Message ID",
        emoji="Emoji to react with — e.g. ✅ or 👍 or <:custom:123456789>",
        role="Role to give when someone reacts",
        channel="Only needed if you pasted a plain Message ID instead of a full link",
    )
    async def rr_add(
        self,
        interaction: discord.Interaction,
        message_link: str,
        emoji: str,
        role: discord.Role,
        channel: discord.TextChannel = None,
    ):
        await interaction.response.defer(ephemeral=True)

        ch_id, msg_id = parse_link(message_link)
        if ch_id is None:
            if channel is None:
                await interaction.followup.send(
                    "❌ Paste the full message link, or pick the Channel too.", ephemeral=True
                )
                return
            ch_id = channel.id

        if not msg_id:
            await interaction.followup.send("❌ Couldn't parse the message ID.", ephemeral=True)
            return

        target_channel = interaction.guild.get_channel(ch_id)
        if not target_channel:
            await interaction.followup.send("❌ Channel not found.", ephemeral=True)
            return

        try:
            message = await target_channel.fetch_message(msg_id)
        except discord.NotFound:
            await interaction.followup.send(
                "❌ Message not found. Make sure the bot can see that channel.", ephemeral=True
            )
            return
        except Exception as e:
            await interaction.followup.send(f"❌ Couldn't fetch message: {e}", ephemeral=True)
            return

        emoji_str = emoji.strip()
        try:
            await message.add_reaction(emoji_str)
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"❌ Couldn't add reaction `{emoji_str}` — make sure the emoji is valid.\n`{e}`",
                ephemeral=True,
            )
            return

        rr = load_rr()
        key = rr_key(interaction.guild_id, ch_id, msg_id)
        rr.setdefault(key, {"pairs": {}})["pairs"][emoji_str] = role.id
        save_rr(rr)

        embed = discord.Embed(title="✅ Reaction Role Added!", color=config.SUCCESS_COLOR)
        embed.add_field(
            name="📌 Message",
            value=f"[Jump](https://discord.com/channels/{interaction.guild_id}/{ch_id}/{msg_id})",
            inline=True,
        )
        embed.add_field(name="Emoji", value=emoji_str, inline=True)
        embed.add_field(name="Role", value=role.mention, inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Reacting gives {role.name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /reactionrole remove — both fields are autocomplete dropdowns ──────
    @rr.command(name="remove", description="Remove one emoji → role pair from a message")
    @app_commands.describe(message="Pick the message", emoji="Pick the emoji pair to remove")
    async def rr_remove(self, interaction: discord.Interaction, message: str, emoji: str):
        rr = load_rr()
        entry = rr.get(message)
        if not entry or emoji not in entry.get("pairs", {}):
            await interaction.response.send_message("❌ That pair isn't set up (anymore).", ephemeral=True)
            return

        del entry["pairs"][emoji]
        _, ch_id, msg_id = message.split(":")
        if not entry["pairs"]:
            del rr[message]
        save_rr(rr)

        channel = interaction.guild.get_channel(int(ch_id))
        if channel:
            try:
                msg = await channel.fetch_message(int(msg_id))
                await msg.clear_reaction(emoji)
            except Exception:
                pass

        embed = discord.Embed(
            title="🗑️ Reaction Role Removed",
            description=(
                f"`{emoji}` unlinked from "
                f"[that message](https://discord.com/channels/{interaction.guild_id}/{ch_id}/{msg_id})."
            ),
            color=config.ERROR_COLOR,
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @rr_remove.autocomplete("message")
    async def rr_remove_message_autocomplete(self, interaction: discord.Interaction, current: str):
        return _message_choices(interaction, current)

    @rr_remove.autocomplete("emoji")
    async def rr_remove_emoji_autocomplete(self, interaction: discord.Interaction, current: str):
        return _emoji_choices(interaction, current)

    # ── /reactionrole clear — autocomplete dropdown for the message ────────
    @rr.command(name="clear", description="Remove ALL reaction roles from a message")
    @app_commands.describe(message="Pick the message")
    async def rr_clear(self, interaction: discord.Interaction, message: str):
        rr = load_rr()
        if message not in rr:
            await interaction.response.send_message("❌ That message has no reaction roles (anymore).", ephemeral=True)
            return

        del rr[message]
        save_rr(rr)

        _, ch_id, msg_id = message.split(":")
        channel = interaction.guild.get_channel(int(ch_id))
        if channel:
            try:
                msg = await channel.fetch_message(int(msg_id))
                await msg.clear_reactions()
            except Exception:
                pass

        embed = discord.Embed(
            title="🧹 Reaction Roles Cleared",
            description=(
                f"All reaction roles removed from "
                f"[that message](https://discord.com/channels/{interaction.guild_id}/{ch_id}/{msg_id})."
            ),
            color=config.ERROR_COLOR,
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @rr_clear.autocomplete("message")
    async def rr_clear_message_autocomplete(self, interaction: discord.Interaction, current: str):
        return _message_choices(interaction, current)

    # ── /reactionrole list ────────────────────────────────────────────────────
    @rr.command(name="list", description="List all reaction role setups in this server")
    async def rr_list(self, interaction: discord.Interaction):
        try:
            entries = _guild_entries(interaction.guild_id)

            if not entries:
                await interaction.response.send_message(
                    "❌ No reaction roles set up in this server yet.", ephemeral=True
                )
                return

            embed = discord.Embed(
                title="🎭 Reaction Roles",
                color=config.EMBED_COLOR,
            )
            for key, entry in entries.items():
                _, ch_id, msg_id = key.split(":")
                pairs = entry.get("pairs", {})
                if not pairs:
                    continue
                lines = []
                for emoji, role_id in pairs.items():
                    role = interaction.guild.get_role(int(role_id))
                    lines.append(f"{emoji} → {role.mention if role else f'<@&{role_id}>'}")
                embed.add_field(
                    name=f"[Message](https://discord.com/channels/{interaction.guild_id}/{ch_id}/{msg_id})",
                    value="\n".join(lines) or "—",
                    inline=False,
                )
            embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            try:
                await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
            except Exception:
                pass

    # ── Reaction listeners ────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id or payload.user_id == self.bot.user.id:
            return
        rr    = load_rr()
        key   = rr_key(payload.guild_id, payload.channel_id, payload.message_id)
        entry = rr.get(key)
        if not entry:
            return
        emoji_str = str(payload.emoji)
        role_id   = entry.get("pairs", {}).get(emoji_str)
        if not role_id:
            return
        guild  = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id) if guild else None
        role   = guild.get_role(role_id) if guild else None
        if member and role:
            try:
                await member.add_roles(role, reason="Reaction role")
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id or payload.user_id == self.bot.user.id:
            return
        rr    = load_rr()
        key   = rr_key(payload.guild_id, payload.channel_id, payload.message_id)
        entry = rr.get(key)
        if not entry:
            return
        emoji_str = str(payload.emoji)
        role_id   = entry.get("pairs", {}).get(emoji_str)
        if not role_id:
            return
        guild  = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id) if guild else None
        role   = guild.get_role(role_id) if guild else None
        if member and role:
            try:
                await member.remove_roles(role, reason="Reaction role removed")
            except Exception:
                pass


# ─── Autocomplete helpers (module-level so both remove & clear can share) ─────

def _message_choices(interaction: discord.Interaction, current: str):
    entries = _guild_entries(interaction.guild_id)
    current = (current or "").lower()
    choices = []
    for key, entry in entries.items():
        _, ch_id, msg_id = key.split(":")
        channel = interaction.guild.get_channel(int(ch_id))
        pairs = entry.get("pairs", {})
        label = f"#{channel.name if channel else ch_id} — {len(pairs)} pair(s): {' '.join(pairs.keys())}"
        if current in label.lower():
            choices.append(app_commands.Choice(name=label[:100], value=key))
    return choices[:25]


def _emoji_choices(interaction: discord.Interaction, current: str):
    message_key = getattr(interaction.namespace, "message", None)
    if not message_key:
        return []
    rr = load_rr()
    entry = rr.get(message_key, {})
    current = (current or "").lower()
    choices = []
    for emoji, role_id in entry.get("pairs", {}).items():
        role = interaction.guild.get_role(int(role_id))
        label = f"{emoji} → {role.name if role else role_id}"
        if current in label.lower():
            choices.append(app_commands.Choice(name=label[:100], value=emoji))
    return choices[:25]


@app_commands.context_menu(name="➕ Add Reaction Role")
@app_commands.default_permissions(manage_roles=True)
async def ctx_add_reaction_role(interaction: discord.Interaction, message: discord.Message):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ You don't have permission to manage roles.", ephemeral=True)
        return
    await interaction.response.send_modal(RRQuickEmojiModal(message))


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactionRole(bot))
    bot.tree.add_command(ctx_add_reaction_role)
