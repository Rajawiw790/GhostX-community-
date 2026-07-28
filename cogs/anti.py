"""
Protection System — FASTLIFE ROLEPLAY
Anti-Spam / Anti-Link / Anti-Bot in one cog.

Escalation system for Anti-Spam & Anti-Link:
  - Violation #1 & #2 -> temporary mute (timeout)
  - Violation #3      -> kick (and warning counter resets)
Anti-Bot stays immediate kick/ban (no repeated-offense concept for bot joins).
"""

import re
import time
from datetime import timedelta
from collections import defaultdict

import discord
from discord.ext import commands
from discord import app_commands

import config
import db

PROTECTION_COLLECTION = "protection_settings"

LINK_REGEX = re.compile(r"(https?://\S+|www\.\S+|discord\.gg/\S+|discordapp\.com/invite/\S+)", re.IGNORECASE)
INVITE_REGEX = re.compile(r"(discord\.gg/\S+|discord(?:app)?\.com/invite/\S+)", re.IGNORECASE)

DEFAULT_CFG = {
    "antispam": {
        "enabled": False,
        "limit": 5,             # messages
        "interval": 5,          # seconds
        "mute_duration": 300,   # timeout duration per warning (seconds)
        "max_warnings": 3,      # warnings before kick
        "whitelist_roles": [],
        "whitelist_channels": [],
    },
    "antilink": {
        "enabled": False,
        "mute_duration": 300,
        "max_warnings": 3,
        "whitelist_roles": [],
        "whitelist_channels": [],
    },
    "antiinvite": {
        "enabled": False,
        "mute_duration": 300,
        "max_warnings": 3,
        "whitelist_roles": [],
        "whitelist_channels": [],
    },
    "antibot": {
        "enabled": False,
        "action": "kick",       # "kick" | "ban"
        "whitelist_ids": [],
    },
    "log_channel_id": None,
}


def load_cfg() -> dict:
    return db.load(PROTECTION_COLLECTION)


def save_cfg(data: dict):
    db.save(PROTECTION_COLLECTION, data)


class Protection(commands.Cog):
    antispam_group = app_commands.Group(
        name="antispam",
        description="🚫 Manage the anti-spam system",
        default_permissions=discord.Permissions(administrator=True),
    )
    antilink_group = app_commands.Group(
        name="antilink",
        description="🔗 Manage the anti-link system",
        default_permissions=discord.Permissions(administrator=True),
    )
    antiinvite_group = app_commands.Group(
        name="antiinvite",
        description="📩 Manage the anti-invite system",
        default_permissions=discord.Permissions(administrator=True),
    )
    antibot_group = app_commands.Group(
        name="antibot",
        description="🤖 Manage the anti-bot system",
        default_permissions=discord.Permissions(administrator=True),
    )
    warnings_group = app_commands.Group(
        name="warnings",
        description="⚠️ Manage user protection warnings",
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(self, bot):
        self.bot = bot
        # (guild_id, user_id) -> list[timestamps]  (for spam-rate detection)
        self.spam_cache = defaultdict(list)
        # (guild_id, user_id) -> {"antispam": n, "antilink": n}  (escalation counters)
        self.warnings = defaultdict(lambda: defaultdict(int))

    # ─── helpers ─────────────────────────────────────────────────────────────
    def _get_guild_cfg(self, guild_id: int) -> dict:
        data = load_cfg()
        gid = str(guild_id)
        if gid not in data:
            data[gid] = {
                "antispam": dict(DEFAULT_CFG["antispam"]),
                "antilink": dict(DEFAULT_CFG["antilink"]),
                "antiinvite": dict(DEFAULT_CFG["antiinvite"]),
                "antibot": dict(DEFAULT_CFG["antibot"]),
                "log_channel_id": None,
            }
            save_cfg(data)
        return data[gid]

    def _save_guild_cfg(self, guild_id: int, gcfg: dict):
        data = load_cfg()
        data[str(guild_id)] = gcfg
        save_cfg(data)

    async def _log(self, guild: discord.Guild, gcfg: dict, embed: discord.Embed):
        ch_id = gcfg.get("log_channel_id")
        if not ch_id:
            return
        channel = guild.get_channel(ch_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except Exception:
                pass

    @staticmethod
    def _is_whitelisted(member: discord.Member, sub_cfg: dict, channel_id: int) -> bool:
        if member.guild_permissions.administrator:
            return True
        role_ids = {r.id for r in member.roles}
        if role_ids.intersection(set(sub_cfg.get("whitelist_roles", []))):
            return True
        if channel_id in sub_cfg.get("whitelist_channels", []):
            return True
        return False

    async def _handle_violation(
        self,
        member: discord.Member,
        rule_type: str,       # "antispam" | "antilink"
        sub_cfg: dict,
        reason: str,
    ):
        """
        Escalating punishment:
          count < max_warnings -> temporary mute (timeout)
          count >= max_warnings -> kick, counter resets to 0
        Returns (action_taken, count, max_warnings)
        """
        key = (member.guild.id, member.id)
        self.warnings[key][rule_type] += 1
        count = self.warnings[key][rule_type]
        max_warnings = sub_cfg.get("max_warnings", 3)
        mute_duration = sub_cfg.get("mute_duration", 300)

        if count >= max_warnings:
            try:
                await member.kick(reason=f"{reason} — تجاوز {max_warnings} تحذيرات")
            except Exception as e:
                print(f"[Protection] Kick error: {e}")
            self.warnings[key][rule_type] = 0
            return "kick", count, max_warnings
        else:
            try:
                await member.timeout(
                    discord.utils.utcnow() + timedelta(seconds=mute_duration),
                    reason=reason,
                )
            except Exception as e:
                print(f"[Protection] Timeout error: {e}")
            return "mute", count, max_warnings

    # ─── on_message: anti-spam + anti-link ──────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not isinstance(message.author, discord.Member):
            return

        gcfg = self._get_guild_cfg(message.guild.id)
        has_invite = bool(INVITE_REGEX.search(message.content))
        has_link = bool(LINK_REGEX.search(message.content))

        # ── Anti-Invite (Discord server invites specifically) ──
        invite_cfg = gcfg.get("antiinvite", {})
        if (
            invite_cfg.get("enabled")
            and has_invite
            and not self._is_whitelisted(message.author, invite_cfg, message.channel.id)
        ):
            try:
                await message.delete()
            except Exception:
                pass

            action, count, max_warnings = await self._handle_violation(
                message.author, "antiinvite", invite_cfg, "Anti-Invite: posted a server invite"
            )

            try:
                if action == "kick":
                    warn_txt = f"📩 {message.author.mention} تّطرد من السيرفر (تجاوز {max_warnings} تحذيرات ديال الدعوات)."
                else:
                    warn_txt = (
                        f"📩 {message.author.mention} روابط الدعوة ممنوعة! "
                        f"تحذير {count}/{max_warnings} — تّبنّن مؤقتا."
                    )
                await message.channel.send(warn_txt, delete_after=8)
            except Exception:
                pass

            embed = discord.Embed(
                title="📩 Anti-Invite Triggered",
                description=(
                    f"**User:** {message.author.mention}\n"
                    f"**Channel:** {message.channel.mention}\n"
                    f"**Warning:** {count}/{max_warnings}\n"
                    f"**Action:** `{action}`"
                ),
                color=config.ERROR_COLOR,
            )
            await self._log(message.guild, gcfg, embed)
            return  # don't also run anti-link/anti-spam on a message we already deleted

        # ── Anti-Link (any other link, invites are handled separately above) ──
        link_cfg = gcfg.get("antilink", {})
        if (
            link_cfg.get("enabled")
            and has_link
            and not self._is_whitelisted(message.author, link_cfg, message.channel.id)
        ):
            try:
                await message.delete()
            except Exception:
                pass

            action, count, max_warnings = await self._handle_violation(
                message.author, "antilink", link_cfg, "Anti-Link: posted a link"
            )

            try:
                if action == "kick":
                    warn_txt = f"🔗 {message.author.mention} تّطرد من السيرفر (تجاوز {max_warnings} تحذيرات ديال الروابط)."
                else:
                    warn_txt = (
                        f"🔗 {message.author.mention} الروابط ممنوعة! "
                        f"تحذير {count}/{max_warnings} — تّبنّن مؤقتا."
                    )
                await message.channel.send(warn_txt, delete_after=8)
            except Exception:
                pass

            embed = discord.Embed(
                title="🔗 Anti-Link Triggered",
                description=(
                    f"**User:** {message.author.mention}\n"
                    f"**Channel:** {message.channel.mention}\n"
                    f"**Warning:** {count}/{max_warnings}\n"
                    f"**Action:** `{action}`"
                ),
                color=config.ERROR_COLOR,
            )
            await self._log(message.guild, gcfg, embed)
            return  # don't also run anti-spam on a message we already deleted

        # ── Anti-Spam ──
        spam_cfg = gcfg.get("antispam", {})
        if spam_cfg.get("enabled") and not self._is_whitelisted(message.author, spam_cfg, message.channel.id):
            key = (message.guild.id, message.author.id)
            now = time.time()
            interval = spam_cfg.get("interval", 5)
            limit = spam_cfg.get("limit", 5)

            self.spam_cache[key] = [t for t in self.spam_cache[key] if now - t < interval]
            self.spam_cache[key].append(now)

            if len(self.spam_cache[key]) > limit:
                self.spam_cache[key] = []
                try:
                    await message.delete()
                except Exception:
                    pass

                action, count, max_warnings = await self._handle_violation(
                    message.author, "antispam", spam_cfg, "Anti-Spam: message flood"
                )

                try:
                    if action == "kick":
                        warn_txt = f"🚫 {message.author.mention} تّطرد من السيرفر (تجاوز {max_warnings} تحذيرات ديال الفلود)."
                    else:
                        warn_txt = (
                            f"🚫 {message.author.mention} تسالا! "
                            f"تحذير {count}/{max_warnings} — تّبنّن مؤقتا."
                        )
                    await message.channel.send(warn_txt, delete_after=8)
                except Exception:
                    pass

                embed = discord.Embed(
                    title="🚫 Anti-Spam Triggered",
                    description=(
                        f"**User:** {message.author.mention}\n"
                        f"**Channel:** {message.channel.mention}\n"
                        f"**Warning:** {count}/{max_warnings}\n"
                        f"**Action:** `{action}`"
                    ),
                    color=config.ERROR_COLOR,
                )
                await self._log(message.guild, gcfg, embed)

    # ─── on_member_join: anti-bot ────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.bot:
            return

        gcfg = self._get_guild_cfg(member.guild.id)
        bot_cfg = gcfg.get("antibot", {})
        if not bot_cfg.get("enabled"):
            return
        if member.id in bot_cfg.get("whitelist_ids", []):
            return

        action = bot_cfg.get("action", "kick")
        try:
            if action == "ban":
                await member.ban(reason="Anti-Bot: unauthorized bot join")
            else:
                await member.kick(reason="Anti-Bot: unauthorized bot join")
        except Exception as e:
            print(f"[Protection] Anti-Bot error: {e}")
            return

        embed = discord.Embed(
            title="🤖 Anti-Bot Triggered",
            description=f"**Bot:** {member.mention} (`{member.id}`)\n**Action:** `{action}`",
            color=config.ERROR_COLOR,
        )
        await self._log(member.guild, gcfg, embed)

    # ═══════════════════════════ /antispam ═══════════════════════════════════
    @antispam_group.command(name="enable", description="✅ Enable anti-spam")
    async def antispam_enable(self, interaction: discord.Interaction):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        gcfg["antispam"]["enabled"] = True
        self._save_guild_cfg(interaction.guild_id, gcfg)
        await interaction.response.send_message("✅ Anti-Spam فعّال دابا.", ephemeral=True)

    @antispam_group.command(name="disable", description="❌ Disable anti-spam")
    async def antispam_disable(self, interaction: discord.Interaction):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        gcfg["antispam"]["enabled"] = False
        self._save_guild_cfg(interaction.guild_id, gcfg)
        await interaction.response.send_message("❌ Anti-Spam متوقف دابا.", ephemeral=True)

    @antispam_group.command(name="config", description="⚙️ Configure anti-spam thresholds & escalation")
    @app_commands.describe(
        limit="Max messages allowed within the interval (default 5)",
        interval="Time window in seconds (default 5)",
        mute_duration="Timeout duration per warning, in seconds (default 300)",
        max_warnings="How many warnings before a kick (default 3)",
    )
    async def antispam_config(
        self,
        interaction: discord.Interaction,
        limit: int = None,
        interval: int = None,
        mute_duration: int = None,
        max_warnings: int = None,
    ):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        if limit is not None:         gcfg["antispam"]["limit"] = limit
        if interval is not None:      gcfg["antispam"]["interval"] = interval
        if mute_duration is not None: gcfg["antispam"]["mute_duration"] = mute_duration
        if max_warnings is not None:  gcfg["antispam"]["max_warnings"] = max_warnings
        self._save_guild_cfg(interaction.guild_id, gcfg)
        await interaction.response.send_message(
            embed=self._antispam_embed(gcfg["antispam"]), ephemeral=True
        )

    @antispam_group.command(name="whitelist", description="🛡️ Whitelist a role or channel from anti-spam")
    @app_commands.describe(role="Role to whitelist (optional)", channel="Channel to whitelist (optional)", remove="Remove instead of add")
    async def antispam_whitelist(
        self,
        interaction: discord.Interaction,
        role: discord.Role = None,
        channel: discord.TextChannel = None,
        remove: bool = False,
    ):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        sub = gcfg["antispam"]
        if role:
            lst = sub.setdefault("whitelist_roles", [])
            if remove and role.id in lst: lst.remove(role.id)
            elif not remove and role.id not in lst: lst.append(role.id)
        if channel:
            lst = sub.setdefault("whitelist_channels", [])
            if remove and channel.id in lst: lst.remove(channel.id)
            elif not remove and channel.id not in lst: lst.append(channel.id)
        self._save_guild_cfg(interaction.guild_id, gcfg)
        await interaction.response.send_message("✅ تم تحديث اللائحة البيضاء.", ephemeral=True)

    @antispam_group.command(name="status", description="📊 Show anti-spam settings")
    async def antispam_status(self, interaction: discord.Interaction):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        await interaction.response.send_message(embed=self._antispam_embed(gcfg["antispam"]), ephemeral=True)

    def _antispam_embed(self, sub: dict) -> discord.Embed:
        e = discord.Embed(title="🚫 Anti-Spam Settings", color=config.SUCCESS_COLOR)
        e.add_field(name="Status", value="✅ ON" if sub.get("enabled") else "❌ OFF", inline=True)
        e.add_field(name="Limit", value=f"{sub.get('limit')} msgs / {sub.get('interval')}s", inline=True)
        e.add_field(name="Mute Duration", value=f"{sub.get('mute_duration')}s", inline=True)
        e.add_field(name="Max Warnings", value=f"{sub.get('max_warnings')} (then kick)", inline=True)
        e.add_field(name="Whitelisted Roles", value=str(len(sub.get("whitelist_roles", []))), inline=True)
        e.add_field(name="Whitelisted Channels", value=str(len(sub.get("whitelist_channels", []))), inline=True)
        return e

    # ═══════════════════════════ /antilink ════════════════════════════════════
    @antilink_group.command(name="enable", description="✅ Enable anti-link")
    async def antilink_enable(self, interaction: discord.Interaction):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        gcfg["antilink"]["enabled"] = True
        self._save_guild_cfg(interaction.guild_id, gcfg)
        await interaction.response.send_message("✅ Anti-Link فعّال دابا.", ephemeral=True)

    @antilink_group.command(name="disable", description="❌ Disable anti-link")
    async def antilink_disable(self, interaction: discord.Interaction):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        gcfg["antilink"]["enabled"] = False
        self._save_guild_cfg(interaction.guild_id, gcfg)
        await interaction.response.send_message("❌ Anti-Link متوقف دابا.", ephemeral=True)

    @antilink_group.command(name="config", description="⚙️ Configure anti-link escalation")
    @app_commands.describe(
        mute_duration="Timeout duration per warning, in seconds (default 300)",
        max_warnings="How many warnings before a kick (default 3)",
    )
    async def antilink_config(
        self,
        interaction: discord.Interaction,
        mute_duration: int = None,
        max_warnings: int = None,
    ):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        if mute_duration is not None: gcfg["antilink"]["mute_duration"] = mute_duration
        if max_warnings is not None:  gcfg["antilink"]["max_warnings"] = max_warnings
        self._save_guild_cfg(interaction.guild_id, gcfg)
        await interaction.response.send_message(embed=self._antilink_embed(gcfg["antilink"]), ephemeral=True)

    @antilink_group.command(name="whitelist", description="🛡️ Whitelist a role or channel from anti-link")
    @app_commands.describe(role="Role to whitelist (optional)", channel="Channel to whitelist (optional)", remove="Remove instead of add")
    async def antilink_whitelist(
        self,
        interaction: discord.Interaction,
        role: discord.Role = None,
        channel: discord.TextChannel = None,
        remove: bool = False,
    ):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        sub = gcfg["antilink"]
        if role:
            lst = sub.setdefault("whitelist_roles", [])
            if remove and role.id in lst: lst.remove(role.id)
            elif not remove and role.id not in lst: lst.append(role.id)
        if channel:
            lst = sub.setdefault("whitelist_channels", [])
            if remove and channel.id in lst: lst.remove(channel.id)
            elif not remove and channel.id not in lst: lst.append(channel.id)
        self._save_guild_cfg(interaction.guild_id, gcfg)
        await interaction.response.send_message("✅ تم تحديث اللائحة البيضاء.", ephemeral=True)

    @antilink_group.command(name="status