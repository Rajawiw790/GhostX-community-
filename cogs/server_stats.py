"""
Server Stats — Ghostx Community
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/serverstats setup [invite]  — Create live-update stat channels
/serverstats remove          — Remove stat channels
/serverstats update          — Force refresh channel names now

Channels created:
  👥 • Members: 1234
  🤖 • Bots: 5
  🖇️ • discord.gg/xxxxx
"""

import discord
from discord.ext import commands
from discord import app_commands
from discord.ext import tasks
import config
import db
from datetime import datetime

SERVER_STATS_COLLECTION = "server_stats"


def _load() -> dict:
    return db.load(SERVER_STATS_COLLECTION)


def _save(data: dict):
    db.save(SERVER_STATS_COLLECTION, data)


class ServerStats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data: dict = _load()
        self.auto_update.start()

    async def cog_unload(self):
        self.auto_update.cancel()

    # ── Background task — every 5 minutes ────────────────────────────────────
    @tasks.loop(minutes=5)
    async def auto_update(self):
        await self._refresh_all()

    @auto_update.before_loop
    async def before_auto_update(self):
        await self.bot.wait_until_ready()

    async def _refresh_all(self):
        changed = False
        for guild_id_str, cfg in list(self.data.items()):
            try:
                guild = self.bot.get_guild(int(guild_id_str))
                if not guild:
                    continue
                await self._update_guild(guild, cfg)
            except Exception as e:
                print(f"[ServerStats] Error updating {guild_id_str}: {e}")
        if changed:
            _save(self.data)

    async def _update_guild(self, guild: discord.Guild, cfg: dict):
        members   = [m for m in guild.members if not m.bot]
        bots      = [m for m in guild.members if m.bot]
        invite    = cfg.get("invite", "")

        names = {
            "members_ch": f"👥 • Members: {len(members):,}",
            "bots_ch":    f"🤖 • Bots: {len(bots):,}",
            "link_ch":    f"🖇️ • {invite}" if invite else "🖇️ • No invite set",
        }

        for key, new_name in names.items():
            ch_id = cfg.get(key)
            if not ch_id:
                continue
            ch = guild.get_channel(ch_id)
            if ch and ch.name != new_name:
                try:
                    await ch.edit(name=new_name, reason="ServerStats auto-update")
                except Exception:
                    pass

    # ── /serverstats setup ────────────────────────────────────────────────────
    stats_group = app_commands.Group(
        name="serverstats",
        description="📊 Server statistics voice channels",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @stats_group.command(name="setup", description="📊 Create live stat voice channels")
    @app_commands.describe(
        invite="Discord invite link (e.g. discord.gg/ghostx)",
        category="Category to create the channels in (leave blank = new category)",
    )
    async def setup(
        self,
        interaction: discord.Interaction,
        invite: str = "",
        category: discord.CategoryChannel = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        gid   = str(guild.id)

        # Remove existing if any
        old = self.data.get(gid, {})
        for key in ("members_ch", "bots_ch", "link_ch"):
            ch_id = old.get(key)
            if ch_id:
                ch = guild.get_channel(ch_id)
                if ch:
                    try:
                        await ch.delete(reason="ServerStats replaced")
                    except Exception:
                        pass

        # Create or use category
        if not category:
            try:
                category = await guild.create_category(
                    "📊 Server Stats",
                    reason="ServerStats setup",
                )
            except discord.Forbidden:
                await interaction.followup.send("❌ Missing permission to create categories.", ephemeral=True)
                return

        # Overwrites: nobody can join/speak (display-only)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True),
            guild.me: discord.PermissionOverwrite(connect=True, manage_channels=True),
        }

        members = [m for m in guild.members if not m.bot]
        bots    = [m for m in guild.members if m.bot]
        inv_str = invite.strip() if invite.strip() else "discord.gg/ghostx"

        ch_members = await guild.create_voice_channel(
            name=f"👥 • Members: {len(members):,}",
            category=category,
            overwrites=overwrites,
            reason="ServerStats setup",
        )
        ch_bots = await guild.create_voice_channel(
            name=f"🤖 • Bots: {len(bots):,}",
            category=category,
            overwrites=overwrites,
            reason="ServerStats setup",
        )
        ch_link = await guild.create_voice_channel(
            name=f"🖇️ • {inv_str}",
            category=category,
            overwrites=overwrites,
            reason="ServerStats setup",
        )

        self.data[gid] = {
            "invite": inv_str,
            "category": category.id,
            "members_ch": ch_members.id,
            "bots_ch":    ch_bots.id,
            "link_ch":    ch_link.id,
        }
        _save(self.data)

        embed = discord.Embed(
            title="✅ Server Stats — Setup Complete",
            color=config.SUCCESS_COLOR,
            timestamp=datetime.now(),
        )
        embed.add_field(name="👥 Members Channel", value=ch_members.mention, inline=True)
        embed.add_field(name="🤖 Bots Channel",    value=ch_bots.mention,    inline=True)
        embed.add_field(name="🖇️ Link Channel",    value=ch_link.mention,    inline=True)
        embed.add_field(
            name="⏱️ Auto-Update",
            value="Every **5 minutes** automatically",
            inline=False,
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /serverstats remove ───────────────────────────────────────────────────
    @stats_group.command(name="remove", description="🗑️ Remove stat channels")
    async def remove(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        gid = str(interaction.guild.id)
        cfg = self.data.pop(gid, {})
        if not cfg:
            await interaction.followup.send("❌ لم يتم إعداد نظام الإحصائيات في هذا السيرفر.", ephemeral=True)
            return

        deleted = 0
        for key in ("members_ch", "bots_ch", "link_ch"):
            ch_id = cfg.get(key)
            if ch_id:
                ch = interaction.guild.get_channel(ch_id)
                if ch:
                    try:
                        await ch.delete(reason="ServerStats removed")
                        deleted += 1
                    except Exception:
                        pass

        _save(self.data)
        embed = discord.Embed(
            description=f"✅ تم حذف **{deleted}** قنوات إحصائية.",
            color=config.SUCCESS_COLOR,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /serverstats update ───────────────────────────────────────────────────
    @stats_group.command(name="update", description="🔄 Force refresh stat channels now")
    async def update(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        gid = str(interaction.guild.id)
        cfg = self.data.get(gid)
        if not cfg:
            await interaction.followup.send("❌ لم يتم إعداد نظام الإحصائيات بعد. استخدم `/serverstats setup`", ephemeral=True)
            return

        await self._update_guild(interaction.guild, cfg)
        embed = discord.Embed(
            description="✅ تم تحديث قنوات الإحصائيات.",
            color=config.SUCCESS_COLOR,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerStats(bot))
