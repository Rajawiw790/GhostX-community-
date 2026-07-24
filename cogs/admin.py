"""
Admin Commands — Ghostx Community
─────────────────────────────────
Slash commands, each with a matching text shortcut (no slash needed):
  /ban      -> banih @member [reason]
  /kick     -> kickih @member [reason]
  /mute     -> muteih @member [minutes] [reason]
  /unmute   -> unmuteih @member
  /warn     -> warnih @member reason
  /lock     -> lockih
  /unlock   -> unlockih
  /clear    -> cls / clr [amount]

Also: /unban, /nickname, /warnings (view/clear), /nuke, /slowmode, /role.

Slash commands and text shortcuts both call the same internal _do_* methods,
so the moderation logic (hierarchy checks, DMs, permission handling) only
lives in one place.
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import db
from datetime import datetime, timedelta

WARN_COLLECTION = "mod_warnings"

# ─── custom emojis (uploaded by ghostx_1x on the FastLife/Ghostx server) ───
EMOJI = {
    "ban": "<:fl_ban:1528968895812206723>",
    "unban": "<:squarecheckmark:1530119784878964786>",
    "kick": "<:modswords:1530120046830157834>",
    "mute": "<:muted:1530119976361398433>",
    "unmute": "<:ouvert:1530119863555854437>",
    "warn": "<:warning:1530119891326079118>",
    "warnings": "<:staffadmin:1530120140522524672>",
    "lock": "<:lockids:1530120245694566410>",
    "unlock": "<:ouvert:1530119863555854437>",
    "clear": "<:supprimer:1530119918660354139>",
    "nuke": "<:forbidden:1528968907530965013>",
    "slowmode": "<:settings:1530119866366034010>",
    "role_add": "<:roleids:1530119978773381192>",
    "role_remove": "<:roleids:1530120044606918838>",
    "nickname": "<:profil:1530119896380215438>",
    "success": "<:checkmark:1530119810061439107>",
    "error": "<:x:1530119812515106928>",
}


def load_warnings() -> dict:
    return db.load(WARN_COLLECTION)


def save_warnings(data: dict):
    db.save(WARN_COLLECTION, data)


def _add_warning(guild_id: int, user_id: int, reason: str, by_id: int) -> int:
    data = load_warnings()
    gid, uid = str(guild_id), str(user_id)
    data.setdefault(gid, {}).setdefault(uid, [])
    data[gid][uid].append({"reason": reason, "by": by_id, "at": datetime.now().timestamp()})
    save_warnings(data)
    return len(data[gid][uid])


class Admin(commands.Cog):
    TEXT_TRIGGERS = {"lockih", "unlockih", "kickih", "banih", "muteih", "unmuteih", "warnih", "cls", "clr"}

    def __init__(self, bot):
        self.bot = bot

    # ─── shared helpers ─────────────────────────────────────────────────
    def _embed(self, description: str, color=None) -> discord.Embed:
        e = discord.Embed(description=description, color=color or config.EMBED_COLOR, timestamp=datetime.now())
        e.set_footer(text=config.BOT_NAME)
        return e

    def _can_act_on(self, actor: discord.Member, target: discord.Member) -> bool:
        return actor == actor.guild.owner or target.top_role < actor.top_role

    async def _dm(self, member: discord.Member, description: str):
        try:
            await member.send(embed=self._embed(description))
        except Exception:
            pass

    # ─── shared moderation actions ─────────────────────────────────────
    async def _do_ban(self, actor: discord.Member, member: discord.Member, reason: str, delete_days: int = 0) -> str:
        if not self._can_act_on(actor, member):
            return f"{EMOJI['error']} You cannot ban someone with an equal or higher role."
        await self._dm(member, f"You were banned from {actor.guild.name}.\nReason: {reason}")
        try:
            await member.ban(reason=f"{reason} | By: {actor}", delete_message_days=max(0, min(7, delete_days)))
        except discord.Forbidden:
            return f"{EMOJI['error']} I don't have permission to ban this member."
        return f"{EMOJI['ban']} {member.mention} (`{member.id}`) has been banned.\nReason: {reason}\nBy: {actor.mention}"

    async def _do_kick(self, actor: discord.Member, member: discord.Member, reason: str) -> str:
        if not self._can_act_on(actor, member):
            return f"{EMOJI['error']} You cannot kick someone with an equal or higher role."
        await self._dm(member, f"You were kicked from {actor.guild.name}.\nReason: {reason}")
        try:
            await member.kick(reason=f"{reason} | By: {actor}")
        except discord.Forbidden:
            return f"{EMOJI['error']} I don't have permission to kick this member."
        return f"{EMOJI['kick']} {member.mention} (`{member.id}`) has been kicked.\nReason: {reason}\nBy: {actor.mention}"

    async def _do_mute(self, actor: discord.Member, member: discord.Member, minutes: int, reason: str) -> str:
        if not self._can_act_on(actor, member):
            return f"{EMOJI['error']} You cannot mute someone with an equal or higher role."
        minutes = max(1, min(40320, minutes))  # 28 days max
        try:
            await member.timeout(discord.utils.utcnow() + timedelta(minutes=minutes), reason=f"{reason} | By: {actor}")
        except discord.Forbidden:
            return f"{EMOJI['error']} I don't have permission to mute this member."
        return f"{EMOJI['mute']} {member.mention} has been muted for **{minutes} minutes**.\nReason: {reason}\nBy: {actor.mention}"

    async def _do_unmute(self, actor: discord.Member, member: discord.Member) -> str:
        try:
            await member.timeout(None, reason=f"Unmuted by {actor}")
        except discord.Forbidden:
            return f"{EMOJI['error']} I don't have permission to unmute this member."
        return f"{EMOJI['unmute']} {member.mention} has been unmuted.\nBy: {actor.mention}"

    async def _do_warn(self, actor: discord.Member, member: discord.Member, reason: str) -> str:
        count = _add_warning(actor.guild.id, member.id, reason, actor.id)
        await self._dm(member, f"You received a warning in {actor.guild.name}.\nReason: {reason}")
        return f"{EMOJI['warn']} {member.mention} has been warned (total: {count}).\nReason: {reason}\nBy: {actor.mention}"

    async def _do_lock(self, actor: discord.Member, channel: discord.TextChannel, reason: str) -> str:
        overwrite = channel.overwrites_for(actor.guild.default_role)
        overwrite.send_messages = False
        try:
            await channel.set_permissions(actor.guild.default_role, overwrite=overwrite, reason=f"{reason} | By: {actor}")
        except discord.Forbidden:
            return f"{EMOJI['error']} I don't have permission to lock this channel."
        return f"{EMOJI['lock']} {channel.mention} has been locked.\nBy: {actor.mention}"

    async def _do_unlock(self, actor: discord.Member, channel: discord.TextChannel) -> str:
        overwrite = channel.overwrites_for(actor.guild.default_role)
        overwrite.send_messages = None
        try:
            await channel.set_permissions(actor.guild.default_role, overwrite=overwrite, reason=f"Unlocked by {actor}")
        except discord.Forbidden:
            return f"{EMOJI['error']} I don't have permission to unlock this channel."
        return f"{EMOJI['unlock']} {channel.mention} has been unlocked.\nBy: {actor.mention}"

    # ─── text-trigger shortcuts (no slash) ──────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        words = message.content.strip().split()
        if not words or words[0].lower() not in self.TEXT_TRIGGERS:
            return
        trigger = words[0].lower()

        if trigger == "lockih":
            if message.author.guild_permissions.manage_channels:
                result = await self._do_lock(message.author, message.channel, "No reason provided")
                await message.channel.send(embed=self._embed(result))
        elif trigger == "unlockih":
            if message.author.guild_permissions.manage_channels:
                result = await self._do_unlock(message.author, message.channel)
                await message.channel.send(embed=self._embed(result))
        elif trigger == "kickih":
            await self._trigger_member_action(message, "kick_members", self._do_kick)
        elif trigger == "banih":
            await self._trigger_member_action(message, "ban_members", self._do_ban)
        elif trigger == "warnih":
            await self._trigger_member_action(message, "moderate_members", self._do_warn)
        elif trigger == "unmuteih":
            await self._trigger_member_action(message, "moderate_members", self._do_unmute, needs_reason=False)
        elif trigger == "muteih":
            await self._trigger_mute(message)
        elif trigger in ("cls", "clr"):
            await self._trigger_clear(message)

    def _extract_member_and_words(self, message: discord.Message) -> tuple[discord.Member | None, list[str]]:
        member = message.mentions[0] if message.mentions else None
        words = [w for w in message.content.split()[1:] if not w.startswith("<@")]
        return member, words

    async def _trigger_member_action(self, message: discord.Message, perm: str, action, needs_reason: bool = True):
        if not getattr(message.author.guild_permissions, perm):
            return
        member, words = self._extract_member_and_words(message)
        if not member:
            await message.channel.send(f"Mention the member, e.g. `{message.content.split()[0]} @user reason`", delete_after=8)
            return
        if needs_reason:
            reason = " ".join(words) if words else "No reason provided"
            result = await action(message.author, member, reason)
        else:
            result = await action(message.author, member)
        await message.channel.send(embed=self._embed(result))

    async def _trigger_mute(self, message: discord.Message):
        if not message.author.guild_permissions.moderate_members:
            return
        member, words = self._extract_member_and_words(message)
        if not member:
            await message.channel.send("Mention the member, e.g. `muteih @user 30 reason`", delete_after=8)
            return
        minutes = 10
        if words and words[0].isdigit():
            minutes = int(words[0])
            words = words[1:]
        reason = " ".join(words) if words else "No reason provided"
        result = await self._do_mute(message.author, member, minutes, reason)
        await message.channel.send(embed=self._embed(result))

    async def _trigger_clear(self, message: discord.Message):
        if not message.author.guild_permissions.manage_messages:
            return
        parts = message.content.strip().split()
        try:
            amount = max(1, min(100, int(parts[1]))) if len(parts) > 1 else 10
        except ValueError:
            amount = 10
        try:
            await message.delete()
            deleted = await message.channel.purge(limit=amount)
            confirm = await message.channel.send(
                embed=self._embed(f"{EMOJI['clear']} Deleted **{len(deleted)}** messages.\nBy: {message.author.mention}", config.SUCCESS_COLOR)
            )
            await confirm.delete(delay=4)
        except discord.Forbidden:
            pass

    # ═══════════════════════════ slash commands ═══════════════════════════

    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.describe(member="Member to ban", reason="Reason for the ban", delete_days="Delete messages from the last X days (0-7)")
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided", delete_days: int = 0):
        result = await self._do_ban(interaction.user, member, reason, delete_days)
        await interaction.response.send_message(embed=self._embed(result, config.ERROR_COLOR))

    @app_commands.command(name="unban", description="Unban a user by ID")
    @app_commands.describe(user_id="The user ID to unban", reason="Reason for the unban")
    @app_commands.default_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message(embed=self._embed(f"{EMOJI['error']} Invalid user ID.", config.ERROR_COLOR), ephemeral=True)
            return
        try:
            await interaction.guild.unban(discord.Object(id=uid), reason=f"{reason} | By: {interaction.user}")
        except discord.NotFound:
            await interaction.response.send_message(embed=self._embed(f"{EMOJI['error']} That user isn't banned.", config.ERROR_COLOR), ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.response.send_message(embed=self._embed(f"{EMOJI['error']} I don't have permission to unban.", config.ERROR_COLOR), ephemeral=True)
            return
        await interaction.response.send_message(
            embed=self._embed(f"{EMOJI['unban']} User `{uid}` has been unbanned.\nBy: {interaction.user.mention}", config.SUCCESS_COLOR)
        )

    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.describe(member="Member to kick", reason="Reason for the kick")
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        result = await self._do_kick(interaction.user, member, reason)
        await interaction.response.send_message(embed=self._embed(result, config.WARNING_COLOR))

    @app_commands.command(name="warn", description="Warn a member")
    @app_commands.describe(member="Member to warn", reason="Reason for the warning")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        result = await self._do_warn(interaction.user, member, reason)
        await interaction.response.send_message(embed=self._embed(result, config.WARNING_COLOR))

    warnings_group = app_commands.Group(
        name="warnings",
        description="View or clear a member's warning history",
        default_permissions=discord.Permissions(moderate_members=True),
    )

    @warnings_group.command(name="view", description="Show a member's warning history")
    @app_commands.describe(member="The member to check")
    async def warnings_view(self, interaction: discord.Interaction, member: discord.Member):
        entries = load_warnings().get(str(interaction.guild_id), {}).get(str(member.id), [])
        if not entries:
            await interaction.response.send_message(embed=self._embed(f"{EMOJI['warnings']} {member.mention} has no warnings."), ephemeral=True)
            return
        lines = []
        for i, w in enumerate(entries[-10:], 1):
            by = interaction.guild.get_member(w["by"])
            when = datetime.fromtimestamp(w["at"]).strftime("%Y-%m-%d")
            lines.append(f"{i}. {w['reason']} — by {by.mention if by else w['by']} ({when})")
        embed = self._embed("\n".join(lines))
        embed.title = f"{EMOJI['warnings']} Warnings — {member.display_name} ({len(entries)} total)"
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @warnings_group.command(name="clear", description="Clear a member's warning history")
    @app_commands.describe(member="The member to clear")
    async def warnings_clear(self, interaction: discord.Interaction, member: discord.Member):
        data = load_warnings()
        gid = str(interaction.guild_id)
        if gid in data and str(member.id) in data[gid]:
            data[gid].pop(str(member.id))
            save_warnings(data)
        await interaction.response.send_message(
            embed=self._embed(f"{EMOJI['success']} Cleared warnings for {member.mention}.", config.SUCCESS_COLOR), ephemeral=True
        )

    @app_commands.command(name="mute", description="Timeout (mute) a member")
    @app_commands.describe(member="Member to mute", duration="Duration in minutes", reason="Reason for the mute")
    @app_commands.default_permissions(moderate_members=True)
    async def mute(self, interaction: discord.Interaction, member: discord.Member, duration: int = 10, reason: str = "No reason provided"):
        result = await self._do_mute(interaction.user, member, duration, reason)
        await interaction.response.send_message(embed=self._embed(result, config.WARNING_COLOR))

    @app_commands.command(name="unmute", description="Remove timeout from a member")
    @app_commands.describe(member="Member to unmute")
    @app_commands.default_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        result = await self._do_unmute(interaction.user, member)
        await interaction.response.send_message(embed=self._embed(result, config.SUCCESS_COLOR))

    @app_commands.command(name="nickname", description="Change a member's nickname")
    @app_commands.describe(member="The member", nickname="New nickname (leave empty to reset)")
    @app_commands.default_permissions(manage_nicknames=True)
    async def nickname(self, interaction: discord.Interaction, member: discord.Member, nickname: str = None):
        if not self._can_act_on(interaction.user, member):
            await interaction.response.send_message(
                embed=self._embed(f"{EMOJI['error']} You cannot edit someone with an equal or higher role.", config.ERROR_COLOR), ephemeral=True
            )
            return
        try:
            await member.edit(nick=nickname, reason=f"By: {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=self._embed(f"{EMOJI['error']} I don't have permission to change that nickname.", config.ERROR_COLOR), ephemeral=True
            )
            return
        desc = f"{member.mention}'s nickname was reset." if not nickname else f"{member.mention}'s nickname is now **{nickname}**."
        await interaction.response.send_message(embed=self._embed(f"{EMOJI['nickname']} {desc}", config.SUCCESS_COLOR))

    @app_commands.command(name="lock", description="Lock a channel (prevent members from sending messages)")
    @app_commands.describe(channel="Channel to lock (defaults to current)", reason="Reason for locking")
    @app_commands.default_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction, channel: discord.TextChannel = None, reason: str = "No reason provided"):
        ch = channel or interaction.channel
        result = await self._do_lock(interaction.user, ch, reason)
        await interaction.response.send_message(embed=self._embed(result, config.ERROR_COLOR))

    @app_commands.command(name="unlock", description="Unlock a channel")
    @app_commands.describe(channel="Channel to unlock (defaults to current)")
    @app_commands.default_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        result = await self._do_unlock(interaction.user, ch)
        await interaction.response.send_message(embed=self._embed(result, config.SUCCESS_COLOR))

    @app_commands.command(name="clear", description="Delete messages from the channel")
    @app_commands.describe(amount="Number of messages to delete (1-100)", member="Only delete messages from this member (optional)")
    @app_commands.default_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int = 10, member: discord.Member = None):
        amount = max(1, min(100, amount))
        await interaction.response.defer(ephemeral=True)
        if member:
            def check(m):
                return m.author == member
            deleted = await interaction.channel.purge(limit=amount * 3, check=check, oldest_first=False)
            deleted = deleted[:amount]
        else:
            deleted = await interaction.channel.purge(limit=amount)
        suffix = f" from {member.mention}" if member else ""
        await interaction.followup.send(
            embed=self._embed(f"{EMOJI['clear']} Deleted **{len(deleted)}** messages{suffix}.\nBy: {interaction.user.mention}", config.SUCCESS_COLOR),
            ephemeral=True,
        )

    @app_commands.command(name="nuke", description="Instantly clear a channel by recreating it")
    @app_commands.describe(channel="Channel to nuke (defaults to current)")
    @app_commands.default_permissions(manage_channels=True)
    async def nuke(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        await interaction.response.defer(ephemeral=True)
        position = ch.position
        new_channel = await ch.clone(reason=f"Nuke by {interaction.user}")
        await new_channel.edit(position=position)
        await ch.delete()
        await new_channel.send(embed=self._embed(f"{EMOJI['nuke']} Channel cleared.\nBy: {interaction.user.mention}", config.SUCCESS_COLOR))
        await interaction.followup.send(embed=self._embed(f"{EMOJI['success']} Done — see {new_channel.mention}."), ephemeral=True)

    @app_commands.command(name="slowmode", description="Set slowmode for a channel")
    @app_commands.describe(seconds="Slowmode delay in seconds (0 to disable, max 21600)", channel="Channel to apply slowmode (optional)")
    @app_commands.default_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, seconds: int, channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        seconds = max(0, min(21600, seconds))
        try:
            await ch.edit(slowmode_delay=seconds)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=self._embed(f"{EMOJI['error']} I don't have permission to edit this channel.", config.ERROR_COLOR), ephemeral=True
            )
            return
        desc = f"Slowmode disabled in {ch.mention}." if seconds == 0 else f"Slowmode set to **{seconds}s** in {ch.mention}."
        await interaction.response.send_message(embed=self._embed(f"{EMOJI['slowmode']} {desc}\nBy: {interaction.user.mention}", config.SUCCESS_COLOR))

    # ─── /role ────────────────────────────────────────────────────────────
    role_group = app_commands.Group(
        name="role",
        description="Add or remove roles from members",
        default_permissions=discord.Permissions(manage_roles=True),
    )

    @role_group.command(name="add", description="Give a role to a member")
    @app_commands.describe(member="Target member", role="Role to give")
    async def role_add(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                embed=self._embed(f"{EMOJI['error']} That role is higher than my highest role.", config.ERROR_COLOR), ephemeral=True
            )
            return
        try:
            await member.add_roles(role, reason=f"By {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=self._embed(f"{EMOJI['error']} I don't have permission to manage roles.", config.ERROR_COLOR), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=self._embed(f"{EMOJI['role_add']} {role.mention} added to {member.mention}.\nBy: {interaction.user.mention}", config.SUCCESS_COLOR)
        )

    @role_group.command(name="remove", description="Remove a role from a member")
    @app_commands.describe(member="Target member", role="Role to remove")
    async def role_remove(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                embed=self._embed(f"{EMOJI['error']} That role is higher than my highest role.", config.ERROR_COLOR), ephemeral=True
            )
            return
        try:
            await member.remove_roles(role, reason=f"By {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=self._embed(f"{EMOJI['error']} I don't have permission to manage roles.", config.ERROR_COLOR), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=self._embed(f"{EMOJI['role_remove']} {role.mention} removed from {member.mention}.\nBy: {interaction.user.mention}", config.SUCCESS_COLOR)
        )


async def setup(bot):
    await bot.add_cog(Admin(bot))
