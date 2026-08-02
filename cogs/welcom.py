"""
Welcome System — Ghostx Community
Short, clean welcome embed with optional animated banner.

BANNER STORAGE:
  - Bdlt l'approche: bla ma nkhzno rabط (Discord CDN link) li kayfout wa9tou,
    daba kankhznou l bytes dyal l'image/gif b base64 f MongoDB, b7al bla9i
    kanخزنو l message. Hakda banner ma3ndou expiration w ma3ndouch 3laqa
    b Railway ephemeral disk (ghadi ybqa mo7taram f kola redeploy).
  - /welcome setup w /welcome update daba kayqadro يقبلو banner_file
    (attachment li katupload direct m3a la commande) bla9i banner_url.
  - banner_url bqa mawjoud ghir l compatibilité m3a l qadim (link khariji
    permanent b7al imgur/catbox) — ila 3titi l'attachment, howa li ghayakhod
    l'aoulawiya.
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import settings
from cogs import emoji_loader
import requests
from io import BytesIO
import base64
import asyncio
from datetime import datetime
import db

WELCOME_COLLECTION = "welcome_settings"

# Mongo documents kaywsl l 16MB, w base64 kazid l 7ajm b ~33%.
# Kanb9au b7al margin daba: 8MB raw (~10.7MB b3d base64) bezzaf kfaya l gifs/pngs 3adiyin.
MAX_BANNER_BYTES = 8 * 1024 * 1024


def load_welcome() -> dict:
    return db.load(WELCOME_COLLECTION)


def save_welcome(data: dict):
    db.save(WELCOME_COLLECTION, data)


class Welcome(commands.Cog):
    welcome_group = app_commands.Group(
        name="welcome",
        description="👋 Manage the welcome system",
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(self, bot):
        self.bot = bot

    # ─── helper: build the discord.File + embed image ref from stored cfg ──
    def _build_banner_file(self, cfg: dict):
        """Returns (discord.File or None, image_url_or_attachment_ref or None)."""
        banner_data = cfg.get("banner_data")
        banner_filename = cfg.get("banner_filename")
        if banner_data and banner_filename:
            try:
                raw = base64.b64decode(banner_data)
                file = discord.File(BytesIO(raw), filename=banner_filename)
                return file, f"attachment://{banner_filename}"
            except Exception as e:
                print(f"[Welcome] Failed to decode stored banner: {e}")
                return None, None

        # Fallback: legacy external URL (no expiry issue only if it's a
        # permanent host like imgur/catbox — NOT a Discord CDN link).
        banner_url = cfg.get("banner_url")
        if banner_url:
            return None, banner_url

        return None, None

    async def _store_banner_attachment(self, attachment: discord.Attachment) -> dict:
        """Downloads the attachment and returns the dict to merge into cfg."""
        if attachment.size > MAX_BANNER_BYTES:
            raise ValueError(
                f"Banner file too big ({attachment.size / 1024 / 1024:.1f}MB). "
                f"Max allowed is {MAX_BANNER_BYTES / 1024 / 1024:.0f}MB."
            )
        raw = await attachment.read()
        encoded = base64.b64encode(raw).decode("ascii")
        return {
            "banner_data": encoded,
            "banner_filename": attachment.filename,
            "banner_url": "",  # clear any legacy link, attachment takes priority
        }

    # ─── on_member_join ─────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        ws = load_welcome()
        guild_id = str(member.guild.id)
        cfg = ws.get(guild_id)
        if not cfg:
            return

        # Auto role
        auto_role_id = cfg.get("auto_role_id")
        if auto_role_id:
            role = member.guild.get_role(auto_role_id)
            if role:
                try:
                    await member.add_roles(role)
                except Exception:
                    pass

        ch_id = cfg.get("channel_id")
        channel = self.bot.get_channel(ch_id) if ch_id else None
        if not channel:
            return

        try:
            custom_msg = cfg.get("message") or ""

            if custom_msg:
                desc = (custom_msg
                    .replace("{user}", member.mention)
                    .replace("{name}", member.display_name)
                    .replace("{server}", member.guild.name)
                    .replace("{count}", str(member.guild.member_count)))
            else:
                desc = f"Welcome {member.mention} 👋\n**Member #{member.guild.member_count}**"

            embed = discord.Embed(
                description=desc,
                color=0x5865F2,
                timestamp=datetime.now()
            )
            embed.set_author(
                name=f"Welcome to {member.guild.name}!",
                icon_url=member.display_avatar.url
            )
            embed.set_thumbnail(url=member.display_avatar.url)

            file, image_ref = self._build_banner_file(cfg)
            if image_ref:
                embed.set_image(url=image_ref)

            embed.set_footer(
                text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}",
                icon_url=self.bot.user.display_avatar.url
            )

            if file:
                await channel.send(content=member.mention, embed=embed, file=file)
            else:
                await channel.send(content=member.mention, embed=embed)

        except Exception as e:
            print(f"[Welcome] Error: {e}")
            try:
                await channel.send(f"👋 Welcome {member.mention} to **{member.guild.name}**!")
            except Exception:
                pass

    # ─── /welcome setup ──────────────────────────────────────────────────────
    @welcome_group.command(name="setup", description="⚙️ Set up the welcome system")
    @app_commands.describe(
        channel="Channel where welcome messages are posted",
        auto_role="Role automatically given to new members (optional)",
        log_channel="Channel for join logs (optional)",
        message="Custom message — use {user} {name} {server} {count} (optional)",
        banner_file="Upload a banner image/gif — stored permanently in the database (optional)",
        banner_url="Legacy: external permanent image link, e.g. imgur/catbox (optional, ignored if banner_file is set)",
    )
    async def welcome_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        auto_role: discord.Role = None,
        log_channel: discord.TextChannel = None,
        message: str = None,
        banner_file: discord.Attachment = None,
        banner_url: str = None,
    ):
        await interaction.response.defer(ephemeral=True)

        data = {
            "channel_id": channel.id,
            "auto_role_id": auto_role.id if auto_role else None,
            "log_channel_id": log_channel.id if log_channel else None,
            "message": message or "",
            "banner_url": banner_url or "",
            "banner_data": "",
            "banner_filename": "",
        }

        if banner_file:
            try:
                data.update(await self._store_banner_attachment(banner_file))
            except ValueError as e:
                await interaction.followup.send(f"❌ {e}", ephemeral=True)
                return

        ws = load_welcome()
        ws[str(interaction.guild_id)] = data
        save_welcome(ws)

        await interaction.followup.send(
            embed=self._summary_embed("✅ Welcome System Set Up!", channel, auto_role, log_channel, data, data["message"]),
            ephemeral=True
        )

    # ─── /welcome update ─────────────────────────────────────────────────────
    @welcome_group.command(name="update", description="✏️ Update welcome settings")
    @app_commands.describe(
        channel="New welcome channel (optional)",
        auto_role="New auto role (optional)",
        log_channel="New log channel (optional)",
        message="New custom message (optional)",
        banner_file="Upload a new banner image/gif — replaces the stored one (optional)",
        banner_url="New external permanent link — send 'reset' to clear the banner entirely (optional)",
    )
    async def welcome_update(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
        auto_role: discord.Role = None,
        log_channel: discord.TextChannel = None,
        message: str = None,
        banner_file: discord.Attachment = None,
        banner_url: str = None,
    ):
        await interaction.response.defer(ephemeral=True)

        ws = load_welcome()
        guild_id = str(interaction.guild_id)
        cfg = ws.get(guild_id)
        if not cfg:
            await interaction.followup.send("❌ Welcome system is not set up yet. Use `/welcome setup` first.", ephemeral=True)
            return

        if channel:      cfg["channel_id"]    = channel.id
        if auto_role:    cfg["auto_role_id"]  = auto_role.id
        if log_channel:  cfg["log_channel_id"]= log_channel.id
        if message:      cfg["message"]       = message

        if banner_file:
            try:
                cfg.update(await self._store_banner_attachment(banner_file))
            except ValueError as e:
                await interaction.followup.send(f"❌ {e}", ephemeral=True)
                return
        elif banner_url is not None:
            if banner_url.lower() == "reset":
                cfg["banner_url"] = ""
                cfg["banner_data"] = ""
                cfg["banner_filename"] = ""
            else:
                cfg["banner_url"] = banner_url
                cfg["banner_data"] = ""
                cfg["banner_filename"] = ""

        ws[guild_id] = cfg
        save_welcome(ws)

        ch     = interaction.guild.get_channel(cfg.get("channel_id") or 0)
        role   = interaction.guild.get_role(cfg.get("auto_role_id") or 0)
        log_ch = interaction.guild.get_channel(cfg.get("log_channel_id") or 0)
        await interaction.followup.send(
            embed=self._summary_embed("✅ Welcome Settings Updated!", ch, role, log_ch, cfg, cfg.get("message", "")),
            ephemeral=True
        )

    # ─── /welcome remove ─────────────────────────────────────────────────────
    @welcome_group.command(name="remove", description="🗑️ Remove the welcome system setup")
    async def welcome_remove(self, interaction: discord.Interaction):
        ws = load_welcome()
        ws.pop(str(interaction.guild_id), None)
        save_welcome(ws)
        embed = discord.Embed(
            title="🗑️ Welcome System Removed",
            description="The welcome system has been disabled.",
            color=config.ERROR_COLOR
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─── /welcome preview ────────────────────────────────────────────────────
    @welcome_group.command(name="preview", description="🧪 Preview the welcome message")
    async def welcome_preview(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ws = load_welcome()
        cfg = ws.get(str(interaction.guild_id), {})
        channel = interaction.channel

        custom_msg = cfg.get("message") or ""
        desc = (
            custom_msg
            .replace("{user}", interaction.user.mention)
            .replace("{name}", interaction.user.display_name)
            .replace("{server}", interaction.guild.name)
            .replace("{count}", str(interaction.guild.member_count))
        ) if custom_msg else f"Welcome {interaction.user.mention} 👋\n**Member #{interaction.guild.member_count}**"

        embed = discord.Embed(description=desc, color=0x5865F2, timestamp=datetime.now())
        embed.set_author(name=f"Welcome to {interaction.guild.name}!", icon_url=interaction.user.display_avatar.url)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        file, image_ref = self._build_banner_file(cfg)
        if image_ref:
            embed.set_image(url=image_ref)

        embed.set_footer(text=f"- {config.BOT_NAME}", icon_url=self.bot.user.display_avatar.url)

        if file:
            await channel.send(content=f"🧪 {interaction.user.mention}", embed=embed, file=file)
        else:
            await channel.send(content=f"🧪 {interaction.user.mention}", embed=embed)
        await interaction.followup.send("✅ Preview sent!", ephemeral=True)

    # ─── /welcome info ───────────────────────────────────────────────────────
    @welcome_group.command(name="info", description="📊 Show current welcome system settings")
    async def welcome_info(self, interaction: discord.Interaction):
        ws = load_welcome()
        cfg = ws.get(str(interaction.guild_id), {})
        ch     = interaction.guild.get_channel(cfg.get("channel_id") or 0)
        log_ch = interaction.guild.get_channel(cfg.get("log_channel_id") or 0)
        role   = interaction.guild.get_role(cfg.get("auto_role_id") or 0)
        await interaction.response.send_message(
            embed=self._summary_embed("📊 Welcome System Settings", ch, role, log_ch, cfg, cfg.get("message", "")),
            ephemeral=True
        )

    # ─── helper ─────────────────────────────────────────────────────────────
    def _summary_embed(self, title, channel, auto_role, log_channel, cfg: dict, message) -> discord.Embed:
        embed = discord.Embed(title=title, color=config.SUCCESS_COLOR)
        embed.add_field(name="📢 Channel",    value=channel.mention if channel else "❌ Not set", inline=True)
        embed.add_field(name="📋 Log",        value=log_channel.mention if log_channel else "None", inline=True)
        embed.add_field(name="🏷️ Auto Role",  value=auto_role.mention if auto_role else "None", inline=True)

        if cfg.get("banner_data"):
            banner_status = f"✅ Stored in DB ({cfg.get('banner_filename')})"
        elif cfg.get("banner_url"):
            banner_status = f"[External link]({cfg['banner_url']})"
        else:
            banner_status = "None (embed only)"
        embed.add_field(name="🖼️ Banner", value=banner_status, inline=True)

        embed.add_field(name="✏️ Message", value=message[:200] if message else "Default", inline=False)
        embed.set_footer(text=f"{config.BOT_NAME} | Use /welcome preview to test")
        return embed


async def setup(bot):
    await bot.add_cog(Welcome(bot))
