"""
Protection System — FASTLIFE ROLEPLAY
Anti-Spam / Anti-Link / Anti-Invite / Anti-Bot in one cog.

Escalation system for Anti-Spam & Anti-Link & Anti-Invite:
  - Violation #1 & #2 -> temporary mute (timeout)
  - Violation #3      -> kick (and warning counter resets)
Anti-Bot stays immediate kick/ban (no repeated-offense concept for bot joins).

Everything is managed through a handful of unified commands instead of one
command group per system:
  /enable              — turn ON any combination of systems (dropdown)
  /disable             — turn OFF any combination of systems (dropdown)
  /status              — one embed showing every system's current state
  /config              — pick a system, edit its settings (modal / buttons)
  /protectionwhitelist — whitelist a role/channel/bot for any one system
  /warnings check|reset — per-member spam/link warning counters
  /protectionlog       — set the shared log channel
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

# ─── real GhostX custom emojis — hardcoded IDs pulled from the Dev Portal.
# (No more emoji_loader.TextEmojiMap dependency — that class doesn't exist
# in cogs/emoji_loader.py and was crashing this whole cog on load.) ──────
PROT_EMOJI = {
    "spam": "<:11838warning:1530119891326079118>",
    "link": "<:50494lien:1530120083337379941>",
    "invite": "<:20806partnerids:1530119991628795990>",
    "bot": "<:95805bot:1530120267605737562>",
    "shield": "<:45228cybersecurite:1530120061703032882>",
    "logs": "<:84439logs:1530120218985365645>",
    "success": "<:60226check:1530120112194195558>",
    "error": "<:8118xmark:1530119848494108812>",
    "warning": "<:11838warning:1530119891326079118>",
    "kick": "<:78507punishment:1530120192473169990>",
}

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

# The 4 protection systems, in the order they show up in every dropdown /
# panel. "app_emoji" is the ready-to-use <:name:id> string (see PROT_EMOJI).
PROTECTION_SYSTEMS = [
    {"key": "antispam",   "label": "Anti-Spam",   "emoji": "🚫", "app_emoji": PROT_EMOJI["spam"],   "description": "منع الفلود/السبام فـ الشات"},
    {"key": "antilink",   "label": "Anti-Link",   "emoji": "🔗", "app_emoji": PROT_EMOJI["link"],   "description": "منع الروابط (بلا دعوات ديسكورد)"},
    {"key": "antiinvite", "label": "Anti-Invite", "emoji": "📩", "app_emoji": PROT_EMOJI["invite"], "description": "منع روابط الدعوة ديال سيرفرات أخرى"},
    {"key": "antibot",    "label": "Anti-Bot",    "emoji": "🤖", "app_emoji": PROT_EMOJI["bot"],    "description": "طرد/حظر أي بوت غير مرخص منين يدخل"},
]


def load_cfg() -> dict:
    return db.load(PROTECTION_COLLECTION)


def save_cfg(data: dict):
    db.save(PROTECTION_COLLECTION, data)


class Protection(commands.Cog):
    warnings_group = app_commands.Group(
        name="warnings",
        description="⚠️ Manage user protection warnings",
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(self, bot):
        self.bot = bot
        # (guild_id, user_id) -> list[timestamps]  (for spam-rate detection)
        self.spam_cache = defaultdict(list)
        # (guild_id, user_id) -> {"antispam": n, "antilink": n, ...}  (escalation counters)
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

    def _system_embed(self, key: str, sub: dict) -> discord.Embed:
        sys = next(s for s in PROTECTION_SYSTEMS if s["key"] == key)
        e = discord.Embed(title=f"{sys['app_emoji']} {sys['label']} Settings", color=config.SUCCESS_COLOR)
        e.add_field(name="Status", value="✅ ON" if sub.get("enabled") else "❌ OFF", inline=True)
        if key == "antispam":
            e.add_field(name="Limit", value=f"{sub.get('limit', 5)} msgs / {sub.get('interval', 5)}s", inline=True)
        if key == "antibot":
            e.add_field(name="Action", value=f"`{sub.get('action', 'kick')}`", inline=True)
            e.add_field(name="Whitelisted Bots", value=str(len(sub.get("whitelist_ids", []))), inline=True)
        else:
            e.add_field(name="Mute Duration", value=f"{sub.get('mute_duration', 300)}s", inline=True)
            e.add_field(name="Max Warnings", value=f"{sub.get('max_warnings', 3)} (then kick)", inline=True)
            e.add_field(name="Whitelisted Roles", value=str(len(sub.get("whitelist_roles", []))), inline=True)
            e.add_field(name="Whitelisted Channels", value=str(len(sub.get("whitelist_channels", []))), inline=True)
        return e

    async def _handle_violation(
        self,
        member: discord.Member,
        rule_type: str,       # "antispam" | "antilink" | "antiinvite"
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

    # ─── on_message: anti-invite + anti-link + anti-spam ────────────────────
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
                    warn_txt = f"{PROT_EMOJI['invite']} {message.author.mention} تّطرد من السيرفر (تجاوز {max_warnings} تحذيرات ديال الدعوات)."
                else:
                    warn_txt = (
                        f"{PROT_EMOJI['invite']} {message.author.mention} روابط الدعوة ممنوعة! "
                        f"تحذير {count}/{max_warnings} — تّبنّن مؤقتا."
                    )
                await message.channel.send(warn_txt, delete_after=8)
            except Exception:
                pass

            embed = discord.Embed(
                title=f"{PROT_EMOJI['invite']} Anti-Invite Triggered",
                description=(
                    f"**User:** {message.author.mention}\n"
                    f"**Channel:** {message.channel.mention}\n"
                    f"**Warning:** {count}/{max_warnings}\n"
                    f"**Action:** `{action}`"
                ),
                color=config.ERROR_COLOR,
            )
            await self._log(message.guild, gcfg, embed)
            return

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
                    warn_txt = f"{PROT_EMOJI['link']} {message.author.mention} تّطرد من السيرفر (تجاوز {max_warnings} تحذيرات ديال الروابط)."
                else:
                    warn_txt = (
                        f"{PROT_EMOJI['link']} {message.author.mention} الروابط ممنوعة! "
                        f"تحذير {count}/{max_warnings} — تّبنّن مؤقتا."
                    )
                await message.channel.send(warn_txt, delete_after=8)
            except Exception:
                pass

            embed = discord.Embed(
                title=f"{PROT_EMOJI['link']} Anti-Link Triggered",
                description=(
                    f"**User:** {message.author.mention}\n"
                    f"**Channel:** {message.channel.mention}\n"
                    f"**Warning:** {count}/{max_warnings}\n"
                    f"**Action:** `{action}`"
                ),
                color=config.ERROR_COLOR,
            )
            await self._log(message.guild, gcfg, embed)
            return

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
                        warn_txt = f"{PROT_EMOJI['spam']} {message.author.mention} تّطرد من السيرفر (تجاوز {max_warnings} تحذيرات ديال الفلود)."
                    else:
                        warn_txt = (
                            f"{PROT_EMOJI['spam']} {message.author.mention} تسالا! "
                            f"تحذير {count}/{max_warnings} — تّبنّن مؤقتا."
                        )
                    await message.channel.send(warn_txt, delete_after=8)
                except Exception:
                    pass

                embed = discord.Embed(
                    title=f"{PROT_EMOJI['spam']} Anti-Spam Triggered",
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
            title=f"{PROT_EMOJI['bot']} Anti-Bot Triggered",
            description=f"**Bot:** {member.mention} (`{member.id}`)\n**Action:** `{action}`",
            color=config.ERROR_COLOR,
        )
        await self._log(member.guild, gcfg, embed)

    # ═══════════════ /enable & /disable — unified dropdown panel ═══════════════
    @app_commands.command(name="enable", description="✅ فعّل أي نظام حماية من قائمة")
    @app_commands.default_permissions(administrator=True)
    async def enable_cmd(self, interaction: discord.Interaction):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        await interaction.response.send_message(
            "اختار الحماية لي بغيتي تفعّلها 👇",
            view=ProtectionToggleView(self, gcfg, turn_on=True),
            ephemeral=True,
        )

    @app_commands.command(name="disable", description="❌ وقّف أي نظام حماية من قائمة")
    @app_commands.default_permissions(administrator=True)
    async def disable_cmd(self, interaction: discord.Interaction):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        await interaction.response.send_message(
            "اختار الحماية لي بغيتي توقفها 👇",
            view=ProtectionToggleView(self, gcfg, turn_on=False),
            ephemeral=True,
        )

    # ═══════════════ /status — one embed, all systems at once ══════════════════
    @app_commands.command(name="status", description="📊 عرض حالة جميع أنظمة الحماية")
    @app_commands.default_permissions(administrator=True)
    async def status_cmd(self, interaction: discord.Interaction):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        embed = discord.Embed(title=f"{PROT_EMOJI['shield']} Protection Status", color=config.EMBED_COLOR)

        for sys in PROTECTION_SYSTEMS:
            sub = gcfg.get(sys["key"], {})
            state = "✅ ON" if sub.get("enabled") else "❌ OFF"
            if sys["key"] == "antibot":
                details = f"Action: `{sub.get('action', 'kick')}` • Whitelisted bots: {len(sub.get('whitelist_ids', []))}"
            elif sys["key"] == "antispam":
                details = (
                    f"{sub.get('limit', 5)} msgs/{sub.get('interval', 5)}s • "
                    f"mute {sub.get('mute_duration', 300)}s • max {sub.get('max_warnings', 3)}"
                )
            else:
                details = f"mute {sub.get('mute_duration', 300)}s • max {sub.get('max_warnings', 3)}"
            embed.add_field(name=f"{sys['app_emoji']} {sys['label']} — {state}", value=details, inline=False)

        log_ch = interaction.guild.get_channel(gcfg.get("log_channel_id") or 0)
        embed.set_footer(text=f"{PROT_EMOJI['logs']} Log channel: #{log_ch.name if log_ch else 'not set'} | {config.BOT_NAME}")

        await interaction.response.send_message(embed=embed, view=ConfigView(self), ephemeral=True)

    # ═══════════════ /config — pick a system, edit it in one panel ═════════════
    @app_commands.command(name="config", description="⚙️ عدّل إعدادات أي نظام حماية (بانيل واحد)")
    @app_commands.default_permissions(administrator=True)
    async def config_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "اختار نظام الحماية لي بغيتي تعدل عليه 👇",
            view=ConfigView(self),
            ephemeral=True,
        )

    # ═══════════════ /protectionwhitelist — one command, any system ════════════
    @app_commands.command(name="protectionwhitelist", description="🛡️ Whitelist a role, channel, or bot ID for one protection system")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        system="Which protection system",
        role="Role to whitelist (Anti-Spam / Anti-Link / Anti-Invite)",
        channel="Channel to whitelist (Anti-Spam / Anti-Link / Anti-Invite)",
        bot_id="Bot user ID to whitelist (Anti-Bot only)",
        remove="Remove instead of add",
    )
    @app_commands.choices(system=[
        app_commands.Choice(name="Anti-Spam", value="antispam"),
        app_commands.Choice(name="Anti-Link", value="antilink"),
        app_commands.Choice(name="Anti-Invite", value="antiinvite"),
        app_commands.Choice(name="Anti-Bot", value="antibot"),
    ])
    async def protection_whitelist(
        self,
        interaction: discord.Interaction,
        system: app_commands.Choice[str],
        role: discord.Role = None,
        channel: discord.TextChannel = None,
        bot_id: str = None,
        remove: bool = False,
    ):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        key = system.value
        sub = gcfg.setdefault(key, {})
        changed = []

        if key == "antibot":
            if bot_id:
                try:
                    bid = int(bot_id)
                except ValueError:
                    await interaction.response.send_message("❌ ID غير صحيح.", ephemeral=True)
                    return
                lst = sub.setdefault("whitelist_ids", [])
                if remove and bid in lst:
                    lst.remove(bid)
                elif not remove and bid not in lst:
                    lst.append(bid)
                changed.append(f"Bot `{bid}`")
        else:
            if role:
                lst = sub.setdefault("whitelist_roles", [])
                if remove and role.id in lst:
                    lst.remove(role.id)
                elif not remove and role.id not in lst:
                    lst.append(role.id)
                changed.append(role.mention)
            if channel:
                lst = sub.setdefault("whitelist_channels", [])
                if remove and channel.id in lst:
                    lst.remove(channel.id)
                elif not remove and channel.id not in lst:
                    lst.append(channel.id)
                changed.append(channel.mention)

        if not changed:
            hint = "bot_id" if key == "antibot" else "role و/أو channel"
            await interaction.response.send_message(f"❌ خاصك تعطي {hint}.", ephemeral=True)
            return

        self._save_guild_cfg(interaction.guild_id, gcfg)
        action_txt = "تنحاو" if remove else "تزادو"
        await interaction.response.send_message(
            f"✅ {', '.join(changed)} {action_txt} من whitelist ديال {system.name}.", ephemeral=True
        )

    # ═══════════════════════════ /warnings ════════════════════════════════════
    @warnings_group.command(name="check", description="🔍 Check a member's current spam/link warning count")
    @app_commands.describe(member="The member to check")
    async def warnings_check(self, interaction: discord.Interaction, member: discord.Member):
        key = (interaction.guild_id, member.id)
        w = self.warnings.get(key, {})
        e = discord.Embed(title=f"⚠️ Warnings — {member.display_name}", color=config.SUCCESS_COLOR)
        e.add_field(name="Anti-Spam", value=str(w.get("antispam", 0)), inline=True)
        e.add_field(name="Anti-Link", value=str(w.get("antilink", 0)), inline=True)
        e.add_field(name="Anti-Invite", value=str(w.get("antiinvite", 0)), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @warnings_group.command(name="reset", description="🔄 Reset a member's spam/link warnings")
    @app_commands.describe(member="The member to reset")
    async def warnings_reset(self, interaction: discord.Interaction, member: discord.Member):
        key = (interaction.guild_id, member.id)
        if key in self.warnings:
            self.warnings[key] = defaultdict(int)
        await interaction.response.send_message(f"✅ تم تصفير التحذيرات ديال {member.mention}.", ephemeral=True)

    # ─── shared log channel ─────────────────────────────────────────────────
    @app_commands.command(name="protectionlog", description="📋 Set the log channel for protection events")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(channel="Channel where protection logs will be sent")
    async def protection_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        gcfg = self._get_guild_cfg(interaction.guild_id)
        gcfg["log_channel_id"] = channel.id
        self._save_guild_cfg(interaction.guild_id, gcfg)
        await interaction.response.send_message(f"✅ Log channel تبدل لـ {channel.mention}.", ephemeral=True)


# ═══════════════════════════ Shared UI components ═══════════════════════════

class ProtectionToggleView(discord.ui.View):
    """Backs /enable and /disable — multi-select dropdown of all 4 systems."""
    def __init__(self, cog: "Protection", gcfg: dict, turn_on: bool):
        super().__init__(timeout=60)
        self.add_item(ProtectionToggleSelect(cog, gcfg, turn_on))


class ProtectionToggleSelect(discord.ui.Select):
    def __init__(self, cog: "Protection", gcfg: dict, turn_on: bool):
        self.cog = cog
        self.turn_on = turn_on
        options = [
            discord.SelectOption(
                label=sys["label"],
                value=sys["key"],
                description=sys["description"],
                emoji=sys["app_emoji"],
                default=(gcfg.get(sys["key"], {}).get("enabled") is turn_on),
            )
            for sys in PROTECTION_SYSTEMS
        ]
        super().__init__(
            placeholder="اختار نظام الحماية...",
            options=options,
            min_values=1,
            max_values=len(options),
        )

    async def callback(self, interaction: discord.Interaction):
        gcfg = self.cog._get_guild_cfg(interaction.guild_id)
        changed = []
        for key in self.values:
            gcfg.setdefault(key, {})["enabled"] = self.turn_on
            sys = next(s for s in PROTECTION_SYSTEMS if s["key"] == key)
            changed.append(f"{sys['app_emoji']} {sys['label']}")
        self.cog._save_guild_cfg(interaction.guild_id, gcfg)

        state = "✅ تفعّلو" if self.turn_on else "❌ توقفو"
        await interaction.response.edit_message(
            content=f"{state}: {', '.join(changed)}",
            view=None,
        )


class ConfigView(discord.ui.View):
    """Backs /config and the button-through from /status — single-select
    dropdown that routes to a Modal (numeric settings) or a button panel
    (Anti-Bot's Kick/Ban action) depending on which system is picked."""
    def __init__(self, cog: "Protection"):
        super().__init__(timeout=120)
        self.add_item(ConfigSelect(cog))


class ConfigSelect(discord.ui.Select):
    def __init__(self, cog: "Protection"):
        self.cog = cog
        options = [
            discord.SelectOption(
                label=sys["label"],
                value=sys["key"],
                description=sys["description"],
                emoji=sys["app_emoji"],
            )
            for sys in PROTECTION_SYSTEMS
        ]
        super().__init__(
            placeholder="اختار نظام الحماية باش تعدل عليه...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        gcfg = self.cog._get_guild_cfg(interaction.guild_id)
        sub = gcfg.get(key, {})

        if key == "antibot":
            # No numeric settings to type — just two buttons.
            await interaction.response.edit_message(
                content=f"{PROT_EMOJI['bot']} إعداد Anti-Bot — شنو Action بغيتي فحق البوتات غير المرخصة؟",
                embed=None,
                view=AntiBotConfigView(self.cog),
            )
        else:
            # Numeric fields (mute duration, warnings, etc.) need a modal.
            await interaction.response.send_modal(ProtectionConfigModal(self.cog, key, sub))


class ProtectionConfigModal(discord.ui.Modal):
    """Numeric settings editor for Anti-Spam / Anti-Link / Anti-Invite."""
    def __init__(self, cog: "Protection", key: str, sub: dict):
        sys = next(s for s in PROTECTION_SYSTEMS if s["key"] == key)
        super().__init__(title=f"⚙️ إعداد {sys['label']}")
        self.cog = cog
        self.key = key
        self.is_spam = key == "antispam"

        self.mute_duration = discord.ui.TextInput(
            label="مدة السكوت (بالثواني)",
            default=str(sub.get("mute_duration", 300)),
            max_length=6,
        )
        self.max_warnings = discord.ui.TextInput(
            label="عدد التحذيرات قبل الطرد",
            default=str(sub.get("max_warnings", 3)),
            max_length=2,
        )
        self.add_item(self.mute_duration)
        self.add_item(self.max_warnings)

        if self.is_spam:
            self.limit = discord.ui.TextInput(
                label="عدد الرسائل المسموحة",
                default=str(sub.get("limit", 5)),
                max_length=3,
            )
            self.interval = discord.ui.TextInput(
                label="نافذة القياس (بالثواني)",
                default=str(sub.get("interval", 5)),
                max_length=3,
            )
            self.add_item(self.limit)
            self.add_item(self.interval)

    async def on_submit(self, interaction: discord.Interaction):
        gcfg = self.cog._get_guild_cfg(interaction.guild_id)
        sub = gcfg.setdefault(self.key, {})
        try:
            sub["mute_duration"] = int(self.mute_duration.value)
            sub["max_warnings"] = int(self.max_warnings.value)
            if self.is_spam:
                sub["limit"] = int(self.limit.value)
                sub["interval"] = int(self.interval.value)
        except ValueError:
            await interaction.response.send_message("❌ خاصك تدخل أرقام فقط.", ephemeral=True)
            return

        self.cog._save_guild_cfg(interaction.guild_id, gcfg)
        await interaction.response.send_message(
            embed=self.cog._system_embed(self.key, sub), ephemeral=True
        )


class AntiBotConfigView(discord.ui.View):
    """Kick/Ban buttons for Anti-Bot — no numeric config needed there."""
    def __init__(self, cog: "Protection"):
        super().__init__(timeout=60)
        self.cog = cog

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.primary)
    async def kick_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_action(interaction, "kick")

    @discord.ui.button(label="Ban", style=discord.ButtonStyle.danger)
    async def ban_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_action(interaction, "ban")

    async def _set_action(self, interaction: discord.Interaction, action: str):
        gcfg = self.cog._get_guild_cfg(interaction.guild_id)
        gcfg.setdefault("antibot", {})["action"] = action
        self.cog._save_guild_cfg(interaction.guild_id, gcfg)
        await interaction.response.edit_message(
            content=f"{PROT_EMOJI['bot']} Anti-Bot action تبدلات لـ `{action}`.",
            view=None,
        )


async def setup(bot):
    await bot.add_cog(Protection(bot))
