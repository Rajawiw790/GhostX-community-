"""
Mic Lock System — Ghostx Community
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Anyone who joins the configured voice channel gets server-muted the moment
they connect. They stay muted until someone with the "allow" role (or
Manage Channels) unmutes them — either via the 🎙️ Allow Mic button posted
in the log channel, or the /miclock allow command (works even if the button
already expired / the bot restarted since the request was posted).

/miclock setup   — pick the locked voice channel + who's allowed to unlock mics
/miclock remove  — disable mic lock for this server
/miclock status  — show current config
/miclock allow   — manually unmute a member (button fallback)
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import db

MICLOCK_COLLECTION = "mic_lock"
# Tracks who WE auto-muted, per guild — so we only ever undo mutes we caused
# ourselves (never touch a mute a staff member applied manually for other
# reasons), and so leaving the locked room resets them cleanly.
MUTED_COLLECTION = "mic_lock_muted"


def load_cfg() -> dict:
    return db.load(MICLOCK_COLLECTION)


def save_cfg(data: dict):
    db.save(MICLOCK_COLLECTION, data)


def load_muted() -> dict:
    return db.load(MUTED_COLLECTION)


def save_muted(data: dict):
    db.save(MUTED_COLLECTION, data)


def _has_permission(member: discord.Member, cfg: dict) -> bool:
    """Who can unlock a mic: Manage Channels, or the configured allow role."""
    if member.guild_permissions.manage_channels:
        return True
    allow_role_id = cfg.get("allow_role_id")
    if allow_role_id:
        return any(role.id == allow_role_id for role in member.roles)
    return False


def _track_muted(guild_id: int, member_id: int):
    data = load_muted()
    key = str(guild_id)
    ids = set(data.get(key, []))
    ids.add(member_id)
    data[key] = list(ids)
    save_muted(data)


def _untrack_muted(guild_id: int, member_id: int):
    data = load_muted()
    key = str(guild_id)
    ids = set(data.get(key, []))
    if member_id in ids:
        ids.discard(member_id)
        data[key] = list(ids)
        save_muted(data)


def _is_tracked_muted(guild_id: int, member_id: int) -> bool:
    data = load_muted()
    return member_id in set(data.get(str(guild_id), []))


# ─── "Allow Mic" button — posted per join in the log channel ───────────────
class AllowMicView(discord.ui.View):
    def __init__(self, member_id: int):
        # Not a persistent view (its custom_id isn't unique per-request, and
        # discord.py can't route dynamic per-member custom_ids after a
        # restart without extra machinery). It stays clickable for 10 min,
        # which covers the normal case; /miclock allow is the fallback for
        # anything older or after a bot restart.
        super().__init__(timeout=600)
        self.member_id = member_id

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Allow Mic", emoji="🎙️", style=discord.ButtonStyle.success, custom_id="miclock_allow_btn")
    async def allow(self, interaction: discord.Interaction, button: discord.ui.Button):
        ts = load_cfg()
        cfg = ts.get(str(interaction.guild_id), {})
        if not _has_permission(interaction.user, cfg):
            await interaction.response.send_message("❌ Ma3andekch permission bach t3ti idn l mic.", ephemeral=True)
            return

        member = interaction.guild.get_member(self.member_id)
        if not member:
            await interaction.response.send_message("❌ Member machi f server bqa.", ephemeral=True)
            return

        try:
            await member.edit(mute=False, reason=f"Mic allowed by {interaction.user}")
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed: {e}", ephemeral=True)
            return

        _untrack_muted(interaction.guild_id, self.member_id)

        button.disabled = True
        button.label = f"Allowed by {interaction.user.display_name}"
        embed = interaction.message.embeds[0]
        embed.color = config.SUCCESS_COLOR
        await interaction.response.edit_message(embed=embed, view=self)


# ─── Mic Lock Cog ────────────────────────────────────────────────────────────
class MicLock(commands.Cog):
    miclock_group = app_commands.Group(
        name="miclock",
        description="🎙️ Manage the Mic Lock voice system",
    )

    def __init__(self, bot):
        self.bot = bot

    def _is_staff(self, member: discord.Member) -> bool:
        return member.guild_permissions.manage_channels

    # ── Auto-mute on join / auto-reset on leave ─────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        ts = load_cfg()
        cfg = ts.get(str(member.guild.id))
        if not cfg:
            return
        locked_id = cfg.get("voice_channel_id")
        if not locked_id:
            return

        joined_locked = after.channel and after.channel.id == locked_id and (not before.channel or before.channel.id != locked_id)
        left_locked = before.channel and before.channel.id == locked_id and (not after.channel or after.channel.id != locked_id)

        if joined_locked:
            if _has_permission(member, cfg):
                return  # staff / allow-role members talk freely, no lock needed

            try:
                await member.edit(mute=True, reason="Mic Lock: awaiting permission")
            except Exception as e:
                print(f"[MicLock] failed to mute {member}: {e}")
                return

            _track_muted(member.guild.id, member.id)

            log_channel_id = cfg.get("log_channel_id")
            log_channel = member.guild.get_channel(log_channel_id) if log_channel_id else None
            if log_channel:
                allow_role = member.guild.get_role(cfg.get("allow_role_id") or 0)
                embed = discord.Embed(
                    title="🔒 Mic Locked",
                    description=(
                        f"{member.mention} dkhel l {after.channel.mention}, mic dyalo msdoud.\n"
                        f"{(allow_role.mention + ' ') if allow_role else ''}click bach ta3tih idn."
                    ),
                    color=config.WARNING_COLOR,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
                try:
                    await log_channel.send(embed=embed, view=AllowMicView(member.id))
                except Exception:
                    pass

        elif left_locked:
            # Only reset members WE muted — never touch a mute staff applied
            # manually for an unrelated reason.
            if _is_tracked_muted(member.guild.id, member.id):
                try:
                    await member.edit(mute=False, reason="Mic Lock: left the locked room")
                except Exception:
                    pass
                _untrack_muted(member.guild.id, member.id)

    # ─── /miclock setup ──────────────────────────────────────────────────
    @miclock_group.command(name="setup", description="⚙️ Set up Mic Lock on a voice channel")
    @app_commands.describe(
        voice_channel="The voice channel where joiners get mic-locked",
        allow_role="Role that can grant mic access (optional — Manage Channels always can)",
        log_channel="Text channel where join requests + the Allow button are posted (optional)",
    )
    async def setup_cmd(
        self,
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel,
        allow_role: discord.Role = None,
        log_channel: discord.TextChannel = None,
    ):
        if not self._is_staff(interaction.user):
            await interaction.response.send_message("❌ Manage Channels permission required.", ephemeral=True)
            return

        ts = load_cfg()
        ts[str(interaction.guild_id)] = {
            "voice_channel_id": voice_channel.id,
            "allow_role_id": allow_role.id if allow_role else None,
            "log_channel_id": log_channel.id if log_channel else None,
        }
        save_cfg(ts)

        embed = discord.Embed(title="✅ Mic Lock Set Up", color=config.SUCCESS_COLOR)
        embed.add_field(name="🔊 Voice Channel", value=voice_channel.mention, inline=True)
        embed.add_field(name="🏷️ Allow Role", value=allow_role.mention if allow_role else "Manage Channels only", inline=True)
        embed.add_field(name="📄 Log Channel", value=log_channel.mention if log_channel else "Not set (use /miclock allow)", inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─── /miclock remove ─────────────────────────────────────────────────
    @miclock_group.command(name="remove", description="🗑️ Disable Mic Lock for this server")
    async def remove_cmd(self, interaction: discord.Interaction):
        if not self._is_staff(interaction.user):
            await interaction.response.send_message("❌ Manage Channels permission required.", ephemeral=True)
            return
        ts = load_cfg()
        ts.pop(str(interaction.guild_id), None)
        save_cfg(ts)
        await interaction.response.send_message(
            embed=discord.Embed(description="🗑️ Mic Lock disabled.", color=config.ERROR_COLOR),
            ephemeral=True,
        )

    # ─── /miclock status ─────────────────────────────────────────────────
    @miclock_group.command(name="status", description="ℹ️ Show the current Mic Lock config")
    async def status_cmd(self, interaction: discord.Interaction):
        ts = load_cfg()
        cfg = ts.get(str(interaction.guild_id))
        if not cfg:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Mic Lock machi mconfigure f had server.", color=config.ERROR_COLOR),
                ephemeral=True,
            )
            return
        voice_channel = interaction.guild.get_channel(cfg.get("voice_channel_id") or 0)
        allow_role = interaction.guild.get_role(cfg.get("allow_role_id") or 0)
        log_channel = interaction.guild.get_channel(cfg.get("log_channel_id") or 0)

        embed = discord.Embed(title="ℹ️ Mic Lock Status", color=config.EMBED_COLOR)
        embed.add_field(name="🔊 Voice Channel", value=voice_channel.mention if voice_channel else "❌ Deleted", inline=True)
        embed.add_field(name="🏷️ Allow Role", value=allow_role.mention if allow_role else "Manage Channels only", inline=True)
        embed.add_field(name="📄 Log Channel", value=log_channel.mention if log_channel else "Not set", inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─── /miclock allow — fallback once the button has expired ──────────
    @miclock_group.command(name="allow", description="🎙️ Manually unmute a mic-locked member")
    @app_commands.describe(member="The member to unmute")
    async def allow_cmd(self, interaction: discord.Interaction, member: discord.Member):
        ts = load_cfg()
        cfg = ts.get(str(interaction.guild_id), {})
        if not _has_permission(interaction.user, cfg):
            await interaction.response.send_message("❌ Ma3andekch permission bach t3ti idn l mic.", ephemeral=True)
            return
        try:
            await member.edit(mute=False, reason=f"Mic allowed by {interaction.user}")
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed: {e}", ephemeral=True)
            return
        _untrack_muted(interaction.guild_id, member.id)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"🎙️ {member.mention} t3tah idn l mic dyalo.", color=config.SUCCESS_COLOR)
        )


async def setup(bot):
    await bot.add_cog(MicLock(bot))
