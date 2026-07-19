"""
Admin Commands — Ghostx Community
─────────────────────────────────
/ban   /kick   /warn   /mute   /unmute
/lock  /unlock /clear  /slowmode  /role
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import asyncio
from datetime import datetime, timedelta

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─── helper ─────────────────────────────────────────────────────────────
    def _embed(self, title: str, desc: str, color: int) -> discord.Embed:
        e = discord.Embed(title=title, description=desc, color=color, timestamp=datetime.now())
        e.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        return e

    # ─── text-trigger shortcuts: "lockih" / "kickih @member" — no slash ──────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        words = message.content.strip().split()
        if not words:
            return
        trigger = words[0].lower()

        if trigger == "lockih":
            await self._text_lock(message)
        elif trigger == "kickih":
            await self._text_kick(message)
        elif trigger in ("cls", "clr"):
            await self._text_clear(message)

    async def _text_lock(self, message: discord.Message):
        if not message.author.guild_permissions.manage_channels:
            return
        ch = message.channel
        overwrite = ch.overwrites_for(message.guild.default_role)
        overwrite.send_messages = False
        try:
            await ch.set_permissions(message.guild.default_role, overwrite=overwrite, reason=f"lockih by {message.author}")
            await message.channel.send(embed=self._embed(
                "🔒 Channel Locked",
                f"{ch.mention} has been locked.\n**By:** {message.author.mention}",
                config.ERROR_COLOR
            ))
        except discord.Forbidden:
            await message.channel.send("❌ I don't have permission to lock this channel.")

    async def _text_clear(self, message: discord.Message):
        if not message.author.guild_permissions.manage_messages:
            return
        # parse optional number: "cls 20"
        parts = message.content.strip().split()
        try:
            amount = max(1, min(100, int(parts[1]))) if len(parts) > 1 else 10
        except ValueError:
            amount = 10
        try:
            await message.delete()
            deleted = await message.channel.purge(limit=amount)
            confirm = await message.channel.send(embed=self._embed(
                "🗑️ Messages Deleted",
                f"Deleted **{len(deleted)}** messages.\n**By:** {message.author.mention}",
                config.SUCCESS_COLOR,
            ))
            await confirm.delete(delay=4)
        except discord.Forbidden:
            pass

    async def _text_kick(self, message: discord.Message):
        if not message.author.guild_permissions.kick_members:
            return
        member = message.mentions[0] if message.mentions else None
        if not member:
            await message.channel.send("❌ منشن العضو لي بغيتي تطرد، مثلاً: `kickih @user`", delete_after=8)
            return
        if member.top_role >= message.author.top_role and message.author != message.guild.owner:
            await message.channel.send("❌ ما يمكنش تطرد شخص عندو رتبة مساوية أو أعلى منك.", delete_after=8)
            return
        try:
            await member.kick(reason=f"kickih by {message.author}")
            await message.channel.send(embed=self._embed(
                "👢 Member Kicked",
                f"**User:** {member.mention} (`{member.id}`)\n**By:** {message.author.mention}",
                config.WARNING_COLOR
            ))
        except discord.Forbidden:
            await message.channel.send("❌ ما عنديش صلاحية نطرد هاد العضو.")

    # ─── /ban ────────────────────────────────────────────────────────────────
    @app_commands.command(name="ban", description="🔨 Ban a member from the server")
    @app_commands.describe(member="Member to ban", reason="Reason for the ban", delete_days="Delete messages from last X days (0–7)")
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided", delete_days: int = 0):
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message(
                embed=self._embed("❌ Error", "You cannot ban someone with an equal or higher role.", config.ERROR_COLOR),
                ephemeral=True
            )
            return
        delete_days = max(0, min(7, delete_days))
        try:
            try:
                await member.send(embed=self._embed(
                    f"🔨 You were banned from {interaction.guild.name}",
                    f"**Reason:** {reason}\n**By:** {interaction.user.mention}",
                    config.ERROR_COLOR
                ))
            except Exception:
                pass
            await member.ban(reason=f"{reason} | By: {interaction.user}", delete_message_days=delete_days)
            await interaction.response.send_message(embed=self._embed(
                "🔨 Member Banned",
                f"**User:** {member.mention} (`{member.id}`)\n**Reason:** {reason}\n**By:** {interaction.user.mention}",
                config.ERROR_COLOR
            ))
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=self._embed("❌ Error", "I don't have permission to ban this member.", config.ERROR_COLOR),
                ephemeral=True
            )

    # ─── /kick ───────────────────────────────────────────────────────────────
    @app_commands.command(name="kick", description="👢 Kick a member from the server")
    @app_commands.describe(member="Member to kick", reason="Reason for the kick")
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message(
                embed=self._embed("❌ Error", "You cannot kick someone with an equal or higher role.", config.ERROR_COLOR),
                ephemeral=True
            )
            return
        try:
            try:
                await member.send(embed=self._embed(
                    f"👢 You were kicked from {interaction.guild.name}",
                    f"**Reason:** {reason}\n**By:** {interaction.user.mention}",
                    config.WARNING_COLOR
                ))
            except Exception:
                pass
            await member.kick(reason=f"{reason} | By: {interaction.user}")
            await interaction.response.send_message(embed=self._embed(
                "👢 Member Kicked",
                f"**User:** {member.mention} (`{member.id}`)\n**Reason:** {reason}\n**By:** {interaction.user.mention}",
                config.WARNING_COLOR
            ))
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=self._embed("❌ Error", "I don't have permission to kick this member.", config.ERROR_COLOR),
                ephemeral=True
            )

    # ─── /warn ───────────────────────────────────────────────────────────────
    @app_commands.command(name="warn", description="⚠️ Warn a member")
    @app_commands.describe(member="Member to warn", reason="Reason for the warning")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        try:
            await member.send(embed=self._embed(
                f"⚠️ You received a warning — {interaction.guild.name}",
                f"**Reason:** {reason}\n**By:** {interaction.user.mention}",
                config.WARNING_COLOR
            ))
            dm_sent = True
        except Exception:
            dm_sent = False

        await interaction.response.send_message(embed=self._embed(
            "⚠️ Member Warned",
            f"**User:** {member.mention}\n**Reason:** {reason}\n**By:** {interaction.user.mention}\n{'✅ DM sent' if dm_sent else '⚠️ Could not DM the member'}",
            config.WARNING_COLOR
        ))

    # ─── /mute ───────────────────────────────────────────────────────────────
    @app_commands.command(name="mute", description="🔇 Timeout (mute) a member")
    @app_commands.describe(member="Member to mute", duration="Duration in minutes", reason="Reason for the mute")
    @app_commands.default_permissions(moderate_members=True)
    async def mute(self, interaction: discord.Interaction, member: discord.Member, duration: int = 10, reason: str = "No reason provided"):
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message(
                embed=self._embed("❌ Error", "You cannot mute someone with an equal or higher role.", config.ERROR_COLOR),
                ephemeral=True
            )
            return
        duration = max(1, min(40320, duration))  # max 28 days in minutes
        until = discord.utils.utcnow() + timedelta(minutes=duration)
        try:
            await member.timeout(until, reason=f"{reason} | By: {interaction.user}")
            await interaction.response.send_message(embed=self._embed(
                "🔇 Member Muted",
                f"**User:** {member.mention}\n**Duration:** {duration} minutes\n**Reason:** {reason}\n**By:** {interaction.user.mention}",
                config.WARNING_COLOR
            ))
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=self._embed("❌ Error", "I don't have permission to mute this member.", config.ERROR_COLOR),
                ephemeral=True
            )

    # ─── /unmute ─────────────────────────────────────────────────────────────
    @app_commands.command(name="unmute", description="🔊 Remove timeout from a member")
    @app_commands.describe(member="Member to unmute")
    @app_commands.default_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        try:
            await member.timeout(None, reason=f"Unmuted by {interaction.user}")
            await interaction.response.send_message(embed=self._embed(
                "🔊 Member Unmuted",
                f"**User:** {member.mention}\n**By:** {interaction.user.mention}",
                config.SUCCESS_COLOR
            ))
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=self._embed("❌ Error", "I don't have permission to unmute this member.", config.ERROR_COLOR),
                ephemeral=True
            )

    # ─── /lock ───────────────────────────────────────────────────────────────
    @app_commands.command(name="lock", description="🔒 Lock a channel (prevent members from sending messages)")
    @app_commands.describe(channel="Channel to lock (defaults to current)", reason="Reason for locking")
    @app_commands.default_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction, channel: discord.TextChannel = None, reason: str = "No reason provided"):
        ch = channel or interaction.channel
        overwrite = ch.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        try:
            await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"{reason} | By: {interaction.user}")
            await interaction.response.send_message(embed=self._embed(
                "🔒 Channel Locked",
                f"{ch.mention} has been locked.\n**Reason:** {reason}\n**By:** {interaction.user.mention}",
                config.ERROR_COLOR
            ))
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=self._embed("❌ Error", "I don't have permission to lock this channel.", config.ERROR_COLOR),
                ephemeral=True
            )

    # ─── /unlock ─────────────────────────────────────────────────────────────
    @app_commands.command(name="unlock", description="🔓 Unlock a channel")
    @app_commands.describe(channel="Channel to unlock (defaults to current)", reason="Reason for unlocking")
    @app_commands.default_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction, channel: discord.TextChannel = None, reason: str = "Channel unlocked"):
        ch = channel or interaction.channel
        overwrite = ch.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None  # reset to default
        try:
            await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"{reason} | By: {interaction.user}")
            await interaction.response.send_message(embed=self._embed(
                "🔓 Channel Unlocked",
                f"{ch.mention} has been unlocked.\n**By:** {interaction.user.mention}",
                config.SUCCESS_COLOR
            ))
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=self._embed("❌ Error", "I don't have permission to unlock this channel.", config.ERROR_COLOR),
                ephemeral=True
            )

    # ─── /clear ──────────────────────────────────────────────────────────────
    @app_commands.command(name="clear", description="🗑️ Delete messages from the channel")
    @app_commands.describe(amount="Number of messages to delete (1–100)", member="Only delete messages from this member (optional)")
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
        await interaction.followup.send(embed=self._embed(
            "🗑️ Messages Deleted",
            f"Deleted **{len(deleted)}** messages{f' from {member.mention}' if member else ''}.\n**By:** {interaction.user.mention}",
            config.SUCCESS_COLOR
        ), ephemeral=True)

    # ─── /slowmode ───────────────────────────────────────────────────────────
    @app_commands.command(name="slowmode", description="🐢 Set slowmode for a channel")
    @app_commands.describe(seconds="Slowmode delay in seconds (0 to disable, max 21600)", channel="Channel to apply slowmode (optional)")
    @app_commands.default_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, seconds: int, channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        seconds = max(0, min(21600, seconds))
        try:
            await ch.edit(slowmode_delay=seconds)
            if seconds == 0:
                desc = f"Slowmode disabled in {ch.mention}."
            else:
                desc = f"Slowmode set to **{seconds}s** in {ch.mention}."
            await interaction.response.send_message(embed=self._embed("🐢 Slowmode Updated", desc + f"\n**By:** {interaction.user.mention}", config.SUCCESS_COLOR))
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=self._embed("❌ Error", "I don't have permission to edit this channel.", config.ERROR_COLOR),
                ephemeral=True
            )

    # ─── /role ───────────────────────────────────────────────────────────────
    role_group = app_commands.Group(
        name="role",
        description="🏷️ Add or remove roles from members",
        default_permissions=discord.Permissions(manage_roles=True),
    )

    @role_group.command(name="add", description="➕ Give a role to a member")
    @app_commands.describe(member="Target member", role="Role to give")
    async def role_add(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                embed=self._embed("❌ Error", "That role is higher than my highest role.", config.ERROR_COLOR),
                ephemeral=True
            )
            return
        try:
            await member.add_roles(role, reason=f"By {interaction.user}")
            await interaction.response.send_message(embed=self._embed(
                "✅ Role Added",
                f"**User:** {member.mention}\n**Role:** {role.mention}\n**By:** {interaction.user.mention}",
                config.SUCCESS_COLOR
            ))
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=self._embed("❌ Error", "I don't have permission to manage roles.", config.ERROR_COLOR),
                ephemeral=True
            )

    @role_group.command(name="remove", description="➖ Remove a role from a member")
    @app_commands.describe(member="Target member", role="Role to remove")
    async def role_remove(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                embed=self._embed("❌ Error", "That role is higher than my highest role.", config.ERROR_COLOR),
                ephemeral=True
            )
            return
        try:
            await member.remove_roles(role, reason=f"By {interaction.user}")
            await interaction.response.send_message(embed=self._embed(
                "✅ Role Removed",
                f"**User:** {member.mention}\n**Role:** {role.mention}\n**By:** {interaction.user.mention}",
                config.SUCCESS_COLOR
            ))
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=self._embed("❌ Error", "I don't have permission to manage roles.", config.ERROR_COLOR),
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(Admin(bot))
