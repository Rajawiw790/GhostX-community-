"""
Invite Tracker — Ghostx Community
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tracks who invited who by diffing each guild's invite list on member join,
and attributes the join to whichever invite's use-count went up (or
disappeared, for single-use invites). Leaves are subtracted back from the
original inviter's count automatically.

Commands:
  /invites setup <channel>        — set the log channel for join/leave events
  /invites info [member]          — show a member's invite stats
  /invites leaderboard            — top inviters in this server
  /invites add <member> <amount>  — grant bonus invites (admin correction)
  /invites remove <member> <amount> — remove bonus invites (admin correction)

Storage: db.load("invite_settings") / db.load("invite_data") — same
{guild_id: {...}} shape as every other cog in this project.
"""

import discord
from discord.ext import commands
from discord import app_commands

import config
import db

SETTINGS_COLLECTION = "invite_settings"
DATA_COLLECTION = "invite_data"


# ── storage helpers ──────────────────────────────────────────────────────

def _load_settings() -> dict:
    return db.load(SETTINGS_COLLECTION)


def _save_settings(data: dict):
    db.save(SETTINGS_COLLECTION, data)


def _load_data() -> dict:
    return db.load(DATA_COLLECTION)


def _save_data(data: dict):
    db.save(DATA_COLLECTION, data)


def _get_guild_data(guild_id: int) -> dict:
    data = _load_data()
    gid = str(guild_id)
    if gid not in data:
        data[gid] = {"members": {}, "joined_via": {}}
        _save_data(data)
    return data[gid]


def _save_guild_data(guild_id: int, gdata: dict):
    data = _load_data()
    data[str(guild_id)] = gdata
    _save_data(data)


def _get_member_stats(gdata: dict, user_id: int) -> dict:
    return gdata["members"].get(str(user_id), {"joins": 0, "leaves": 0, "bonus": 0})


def _net(stats: dict) -> int:
    return stats.get("joins", 0) - stats.get("leaves", 0) + stats.get("bonus", 0)


class Invites(commands.Cog):
    invites_group = app_commands.Group(
        name="invites",
        description="Invite tracking — see who brought who to the server",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> {invite_code: discord.Invite}
        self.invite_cache: dict[int, dict[str, discord.Invite]] = {}

    # ── helpers ──────────────────────────────────────────────────────────

    async def _fetch_invites(self, guild: discord.Guild) -> dict[str, discord.Invite]:
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            return {}
        return {inv.code: inv for inv in invites}

    async def _cache_guild(self, guild: discord.Guild):
        self.invite_cache[guild.id] = await self._fetch_invites(guild)

    async def _log(self, guild: discord.Guild, embed: discord.Embed):
        settings = _load_settings()
        cfg = settings.get(str(guild.id))
        if not cfg or not cfg.get("log_channel_id"):
            return
        channel = guild.get_channel(cfg["log_channel_id"])
        if channel:
            try:
                await channel.send(embed=embed)
            except Exception:
                pass

    # ── lifecycle ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._cache_guild(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._cache_guild(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        self.invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        self.invite_cache.get(invite.guild.id, {}).pop(invite.code, None)

    # ── core tracking ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        guild = member.guild
        before = self.invite_cache.get(guild.id, {})
        after = await self._fetch_invites(guild)

        used_invite = None
        for code, old_invite in before.items():
            new_invite = after.get(code)
            if new_invite is None:
                # Invite is gone — most likely a single-use invite that just got consumed
                used_invite = old_invite
                break
            if new_invite.uses > old_invite.uses:
                used_invite = new_invite
                break

        self.invite_cache[guild.id] = after

        gdata = _get_guild_data(guild.id)
        embed = discord.Embed(color=config.SUCCESS_COLOR)

        if used_invite and used_invite.inviter:
            inviter = used_invite.inviter
            stats = _get_member_stats(gdata, inviter.id)
            stats["joins"] = stats.get("joins", 0) + 1
            gdata["members"][str(inviter.id)] = stats
            gdata["joined_via"][str(member.id)] = str(inviter.id)
            _save_guild_data(guild.id, gdata)

            embed.description = (
                f"**{member}** انضم عبر الدعوة ديال **{inviter}**\n"
                f"رصيد {inviter}: **{_net(stats)}** دعوة"
            )
        else:
            embed.description = f"**{member}** انضم — تعذر تحديد الدعوة المستعملة (vanity link أو صلاحية ناقصة)."

        embed.set_footer(text=f"Invite Tracker | {config.DEVELOPER}")
        await self._log(guild, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        gdata = _get_guild_data(guild.id)
        inviter_id = gdata["joined_via"].pop(str(member.id), None)
        if not inviter_id:
            return

        stats = _get_member_stats(gdata, int(inviter_id))
        stats["leaves"] = stats.get("leaves", 0) + 1
        gdata["members"][inviter_id] = stats
        _save_guild_data(guild.id, gdata)

        inviter = guild.get_member(int(inviter_id))
        embed = discord.Embed(
            description=(
                f"**{member}** غادر السيرفر (كان انضم عبر **{inviter or inviter_id}**)\n"
                f"رصيد {inviter or inviter_id}: **{_net(stats)}** دعوة"
            ),
            color=config.ERROR_COLOR,
        )
        embed.set_footer(text=f"Invite Tracker | {config.DEVELOPER}")
        await self._log(guild, embed)

    # ── /invites setup ────────────────────────────────────────────────────

    @invites_group.command(name="setup", description="Set the log channel for invite join/leave events")
    @app_commands.describe(channel="Channel where invite events will be logged")
    async def invites_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        settings = _load_settings()
        gid = str(interaction.guild_id)
        settings.setdefault(gid, {})["log_channel_id"] = channel.id
        _save_settings(settings)
        embed = discord.Embed(
            description=f"Log channel set to {channel.mention}.",
            color=config.SUCCESS_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /invites info ─────────────────────────────────────────────────────

    @invites_group.command(name="info", description="Show a member's invite stats")
    @app_commands.describe(member="The member to check (defaults to you)")
    async def invites_info(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        gdata = _get_guild_data(interaction.guild_id)
        stats = _get_member_stats(gdata, member.id)

        embed = discord.Embed(title=f"Invite Stats — {member.display_name}", color=config.EMBED_COLOR)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Total (net)", value=str(_net(stats)), inline=True)
        embed.add_field(name="Joins", value=str(stats.get("joins", 0)), inline=True)
        embed.add_field(name="Leaves", value=str(stats.get("leaves", 0)), inline=True)
        embed.add_field(name="Bonus", value=str(stats.get("bonus", 0)), inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

        await interaction.response.send_message(embed=embed)

    # ── /invites leaderboard ──────────────────────────────────────────────

    @invites_group.command(name="leaderboard", description="Show the top inviters in this server")
    async def invites_leaderboard(self, interaction: discord.Interaction):
        gdata = _get_guild_data(interaction.guild_id)
        ranked = sorted(
            gdata["members"].items(),
            key=lambda kv: _net(kv[1]),
            reverse=True,
        )
        ranked = [(uid, stats) for uid, stats in ranked if _net(stats) != 0][:10]

        if not ranked:
            await interaction.response.send_message(
                embed=discord.Embed(description="No invite data yet.", color=config.EMBED_COLOR),
                ephemeral=True,
            )
            return

        lines = []
        for i, (uid, stats) in enumerate(ranked, 1):
            member = interaction.guild.get_member(int(uid))
            name = member.mention if member else f"<@{uid}>"
            lines.append(f"`{i}.` {name} — **{_net(stats)}**")

        embed = discord.Embed(
            title="Invite Leaderboard",
            description="\n".join(lines),
            color=config.EMBED_COLOR,
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

    # ── /invites add / remove (admin correction) ─────────────────────────

    @invites_group.command(name="add", description="Grant bonus invites to a member")
    @app_commands.describe(member="The member to credit", amount="How many bonus invites to add")
    async def invites_add(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1000]):
        gdata = _get_guild_data(interaction.guild_id)
        stats = _get_member_stats(gdata, member.id)
        stats["bonus"] = stats.get("bonus", 0) + amount
        gdata["members"][str(member.id)] = stats
        _save_guild_data(interaction.guild_id, gdata)

        embed = discord.Embed(
            description=f"Added **{amount}** bonus invites to {member.mention}. New total: **{_net(stats)}**.",
            color=config.SUCCESS_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @invites_group.command(name="remove", description="Remove bonus invites from a member")
    @app_commands.describe(member="The member to adjust", amount="How many bonus invites to remove")
    async def invites_remove(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1000]):
        gdata = _get_guild_data(interaction.guild_id)
        stats = _get_member_stats(gdata, member.id)
        stats["bonus"] = stats.get("bonus", 0) - amount
        gdata["members"][str(member.id)] = stats
        _save_guild_data(interaction.guild_id, gdata)

        embed = discord.Embed(
            description=f"Removed **{amount}** bonus invites from {member.mention}. New total: **{_net(stats)}**.",
            color=config.WARNING_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Invites(bot))
