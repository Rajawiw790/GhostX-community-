"""
Protection System — Ghostx Community
Anti-Spam / Anti-Link / Anti-Bot in one cog.
"""

import re
import time
import discord
from discord.ext import commands
from discord import app_commands
from collections import defaultdict
import config
import db

PROTECTION_COLLECTION = "protection_settings"

LINK_REGEX = re.compile(r"(https?://\S+|www\.\S+|discord\.gg/\S+|discordapp\.com/invite/\S+)", re.IGNORECASE)
INVITE_REGEX = re.compile(r"(discord\.gg/\S+|discord(?:app)?\.com/invite/\S+)", re.IGNORECASE)

DEFAULT_CFG = {
    "antispam": {
        "enabled": False,
        "limit": 5,          # messages
        "interval": 5,       # seconds
        "action": "timeout", # "timeout" | "kick" | "ban" | "delete_only"
        "duration": 60,      # timeout duration in seconds
        "whitelist_roles": [],
        "whitelist_channels": [],
    },
    "antilink": {
        "enabled": False,
        "action": "delete",  # "delete" | "timeout" | "kick" | "ban"
        "duration": 60,
        "allow_invites": False,
        "whitelist_roles": [],
        "whitelist_channels": [],
    },
    "antibot": {
        "enabled": False,
        "action": "kick",    # "kick" | "ban"
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
    antibot_group = app_commands.Group(
        name="antibot",
        description="🤖 Manage the anti-bot system",
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(self, bot):
        self.bot = bot
        # (guild_id, user_id) -> list[timestamps]
        self.spam_cache = defaultdict(list)

    # ─── helpers ─────────────────────────────────────────────────────────────
    def _get_guild_cfg(self, guild_id: int) -> dict:
        data = load_cfg()
        gid = str(guild_id)
        if gid not in data:
            data[gid] = {
                "antispam": dict(DEFAULT_CFG["antispam"]),
                "antilink": dict(DEFAULT_CFG["antilink"]),
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

    async def _punish(self, member: discord.Member, action: str, duration: int, reason: str):
        try:
            if action == "timeout":
                await member.timeout(discord.utils.utcnow() + discord.timedelta(seconds=duration), reason=reason)
            elif action == "kick":
                await member.kick(reason=reason)
            elif action == "ban":
                await member.ban(reason=reason, delete_message_seconds=0)
        except Exception as e:
            print(f"[Protection] Punish error: {e}")

    # ─── on_message: anti-spam + anti-link ──────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not isinstance(message.author, discord.Member):
            return

        gcfg = self._get_guild_cfg(message.guild.id)

        # ── Anti-Link ──
        link_cfg = gcfg.get("antilink", {})
        if link_cfg.get("enabled") and not self._is_whitelisted(message.author, link_cfg, message.channel.id):
            has_invite = bool(INVITE_REGEX.search(message.content))
            has_link = bool(LINK_REGEX.search(message.content))
            blocked = has_link and not (has_invite is False and link_cfg.get("allow_invites") and not has_invite)
            if has_invite and link_cfg.get("allow_invites"):
                blocked = has_link and not has_invite  # invites allowed, but block other links
            elif has_link:
                blocked = True
            else:
                blocked = False

            if blocked:
                try:
                    await message.delete()
                except Exception:
                    pass
                try:
                    warn = await message.channel.send(
                        f"🔗 {message.author.mention} الروابط ممنوعة فهاد السيرفر!", delete_after=5
                    )
                except Exception:
                    pass

                action = link_cfg.get("action", "delete")
                if action != "delete":
                    await self._punish(message.author, action, link_cfg.get("duration", 60), "Anti-Link: posted a link")

                embed = discord.Embed(
                    title="🔗 Anti-Link Triggered",
                    description=f"**User:** {message.author.mention}\n**Channel:** {message.channel.mention}\n**Action:** `{action}`",
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

                action = spam_cfg.get("action", "timeout")
                if action != "delete_only":
                    await self._punish(message.author, action, spam_cfg.get("duration", 60), "Anti-Spam: message flood")

                try:
                    warn = await message.channel.send(
                        f"🚫 {message.author.mention} تسالا! خصك توقف على الفلود.", delete_after=5
                    )
                except Exception:
                    pass

                embed = discord.Embed(
                    title="🚫 Anti-Spam Triggered",
                    description=f"**User:** {message.author.mention}\n**Channel:** {message.channel.mention}\n**Action:** `{action}`",
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

    @antispam_group.command(name="config", description="⚙️ Configure anti-spam thresholds")
    @app_commands.describe(
        limit="Max messages allowed within the interval (default 5)",
        interval="Time window in seconds (default 5)",
        action="Punishment when triggered",
        duration="Timeout duration in seconds (if action=timeout)",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Timeout", value="timeout"),
        app_commands.Choice(name="Kick", value="kick"),
        app_commands.Choice(name="Ban", value="ban"),
        app_commands.Choice(name="Delete only", value="delete_only"),
    ])
    async def antispam_config(
        self,
        interaction: discord.Interaction,
        limit: int = None,
        interval: int = None,
        action: app_commands.Choice[str] = None,
        duration: int = None,
    ):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        if limit is not None:    gcfg["antispam"]["limit"] = limit
        if interval is not None: gcfg["antispam"]["interval"] = interval
        if action is not None:   gcfg["antispam"]["action"] = action.value
        if duration is not None: gcfg["antispam"]["duration"] = duration
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
        e.add_field(name="Action", value=f"`{sub.get('action')}`", inline=True)
        e.add_field(name="Duration", value=f"{sub.get('duration')}s", inline=True)
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

    @antilink_group.command(name="config", description="⚙️ Configure anti-link action")
    @app_commands.describe(
        action="Punishment when triggered",
        duration="Timeout duration in seconds (if action=timeout)",
        allow_invites="Allow Discord server invite links",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Delete only", value="delete"),
        app_commands.Choice(name="Timeout", value="timeout"),
        app_commands.Choice(name="Kick", value="kick"),
        app_commands.Choice(name="Ban", value="ban"),
    ])
    async def antilink_config(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str] = None,
        duration: int = None,
        allow_invites: bool = None,
    ):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        if action is not None:        gcfg["antilink"]["action"] = action.value
        if duration is not None:      gcfg["antilink"]["duration"] = duration
        if allow_invites is not None: gcfg["antilink"]["allow_invites"] = allow_invites
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

    @antilink_group.command(name="status", description="📊 Show anti-link settings")
    async def antilink_status(self, interaction: discord.Interaction):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        await interaction.response.send_message(embed=self._antilink_embed(gcfg["antilink"]), ephemeral=True)

    def _antilink_embed(self, sub: dict) -> discord.Embed:
        e = discord.Embed(title="🔗 Anti-Link Settings", color=config.SUCCESS_COLOR)
        e.add_field(name="Status", value="✅ ON" if sub.get("enabled") else "❌ OFF", inline=True)
        e.add_field(name="Action", value=f"`{sub.get('action')}`", inline=True)
        e.add_field(name="Duration", value=f"{sub.get('duration')}s", inline=True)
        e.add_field(name="Allow Invites", value="✅" if sub.get("allow_invites") else "❌", inline=True)
        e.add_field(name="Whitelisted Roles", value=str(len(sub.get("whitelist_roles", []))), inline=True)
        e.add_field(name="Whitelisted Channels", value=str(len(sub.get("whitelist_channels", []))), inline=True)
        return e

    # ═══════════════════════════ /antibot ═════════════════════════════════════
    @antibot_group.command(name="enable", description="✅ Enable anti-bot")
    async def antibot_enable(self, interaction: discord.Interaction):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        gcfg["antibot"]["enabled"] = True
        self._save_guild_cfg(interaction.guild_id, gcfg)
        await interaction.response.send_message("✅ Anti-Bot فعّال دابا. أي بوت يدخل بلا ترخيص غادي يتّطرد.", ephemeral=True)

    @antibot_group.command(name="disable", description="❌ Disable anti-bot")
    async def antibot_disable(self, interaction: discord.Interaction):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        gcfg["antibot"]["enabled"] = False
        self._save_guild_cfg(interaction.guild_id, gcfg)
        await interaction.response.send_message("❌ Anti-Bot متوقف دابا.", ephemeral=True)

    @antibot_group.command(name="action", description="⚙️ Set what happens when an unauthorized bot joins")
    @app_commands.choices(action=[
        app_commands.Choice(name="Kick", value="kick"),
        app_commands.Choice(name="Ban", value="ban"),
    ])
    async def antibot_action(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        gcfg["antibot"]["action"] = action.value
        self._save_guild_cfg(interaction.guild_id, gcfg)
        await interaction.response.send_message(f"✅ Action تبدلات لـ `{action.value}`.", ephemeral=True)

    @antibot_group.command(name="whitelist", description="🛡️ Allow a specific bot to join without being kicked")
    @app_commands.describe(bot_id="The bot's user ID", remove="Remove instead of add")
    async def antibot_whitelist(self, interaction: discord.Interaction, bot_id: str, remove: bool = False):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        try:
            bid = int(bot_id)
        except ValueError:
            await interaction.response.send_message("❌ ID غير صحيح.", ephemeral=True)
            return
        lst = gcfg["antibot"].setdefault("whitelist_ids", [])
        if remove and bid in lst:
            lst.remove(bid)
        elif not remove and bid not in lst:
            lst.append(bid)
        self._save_guild