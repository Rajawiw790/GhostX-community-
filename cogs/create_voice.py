"""
Create Voice System — Ghostx Community
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Architecture (matches the screenshots):

  Category: 🎙️ Voice Rooms
  ├── #📋 voice-panel          ← text channel with the public "Join to Create" embed
  └── 🔊 ➕ Create Voice       ← join-to-create VC (permanent — bot recreates if deleted)

  When member joins ➕ Create Voice:
  ├── 🔊 🎙️ {name}'s Room      ← temp voice channel (auto-deleted when empty)
  └── 🔒 #📋 panel • room      ← private text channel, visible ONLY to the owner
                                  Contains the 16-button control panel (Lock / Unlock /
                                  Hide / Show / Limit / Invite / Ban / Permit /
                                  Rename / Bitrate / Region / Template /
                                  Claim / Transfer / Delete)

Admin commands:
  /voicepanel setup   — creates the category + channels (or re-posts the panel)
  /voicepanel info    — show current config + active rooms
  /voicepanel remove  — disable and clean up
"""

import asyncio
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

import config
import db

VOICE_COLLECTION = "create_voice"

# ─── Storage ─────────────────────────────────────────────────────────────────

def _load() -> dict:
    return db.load(VOICE_COLLECTION)

def _save(data: dict):
    db.save(VOICE_COLLECTION, data)

def get_cfg(guild_id: int) -> dict:
    return _load().get(str(guild_id), {})

def set_cfg(guild_id: int, cfg: dict):
    d = _load(); d[str(guild_id)] = cfg; _save(d)

def add_room(guild_id: int, vc_id: int, owner_id: int, panel_ch_id: int, panel_msg_id: int):
    d = _load()
    d.setdefault(str(guild_id), {}).setdefault("rooms", {})[str(vc_id)] = {
        "owner_id":     owner_id,
        "panel_ch_id":  panel_ch_id,
        "panel_msg_id": panel_msg_id,
        "locked":  False,
        "hidden":  False,
        "banned":  [],
        "permitted": [],
    }
    _save(d)

def get_room(guild_id: int, vc_id: int) -> dict | None:
    return _load().get(str(guild_id), {}).get("rooms", {}).get(str(vc_id))

def upd_room(guild_id: int, vc_id: int, **kw):
    d = _load()
    r = d.get(str(guild_id), {}).get("rooms", {}).get(str(vc_id))
    if r: r.update(kw); _save(d)

def del_room(guild_id: int, vc_id: int):
    d = _load()
    d.get(str(guild_id), {}).get("rooms", {}).pop(str(vc_id), None)
    _save(d)

def all_rooms(guild_id: int) -> dict:
    return _load().get(str(guild_id), {}).get("rooms", {})


# ─── Modals ───────────────────────────────────────────────────────────────────

class _TextModal(discord.ui.Modal):
    value = discord.ui.TextInput(label="Value", max_length=100, required=True)
    def __init__(self, title: str, label: str, placeholder: str, callback):
        super().__init__(title=title)
        self.value.label       = label
        self.value.placeholder = placeholder
        self._cb = callback
    async def on_submit(self, interaction: discord.Interaction):
        await self._cb(interaction, self.value.value)

class _IDModal(discord.ui.Modal):
    uid = discord.ui.TextInput(label="Member ID", placeholder="Right-click → Copy ID",
                               min_length=17, max_length=20, required=True)
    def __init__(self, title: str, callback):
        super().__init__(title=title)
        self._cb = callback
    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.uid.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid ID.", ephemeral=True); return
        await self._cb(interaction, uid)


# ─── Control Panel View (16 buttons, 4 rows) ─────────────────────────────────

class VoiceControlView(discord.ui.View):
    """
    Persistent panel posted in the owner's private text channel.
    Buttons mirror the Astro/Scoza layout from the screenshots.
    """
    def __init__(self, vc_id: int = 0, owner_id: int = 0, guild_id: int = 0):
        super().__init__(timeout=None)
        self.vc_id    = vc_id
        self.owner_id = owner_id
        self.guild_id = guild_id
        for btn in self.children:
            if hasattr(btn, "custom_id"):
                btn.custom_id = btn.custom_id.replace("_0", f"_{vc_id}")

    # ── helpers ──────────────────────────────────────────────────────────────
    async def _auth(self, inter: discord.Interaction):
        rd = get_room(inter.guild_id, self.vc_id)
        if not rd:
            await inter.response.send_message("❌ Room data not found.", ephemeral=True)
            return None, None
        if inter.user.id != rd["owner_id"] and not inter.user.guild_permissions.administrator:
            await inter.response.send_message("❌ Only the room owner can do this.", ephemeral=True)
            return None, None
        vc = inter.guild.get_channel(self.vc_id)
        if not vc:
            await inter.response.send_message("❌ Voice channel no longer exists.", ephemeral=True)
            return None, None
        return vc, rd

    async def _reply(self, inter, text):
        if inter.response.is_done():
            await inter.followup.send(text, ephemeral=True)
        else:
            await inter.response.send_message(text, ephemeral=True)

    # ── Row 1 ─────────────────────────────────────────────────────────────────
    @discord.ui.button(emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="vc_lock_0",   row=0)
    async def btn_lock(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        ow = vc.overwrites_for(inter.guild.default_role)
        ow.connect = False
        await vc.set_permissions(inter.guild.default_role, overwrite=ow)
        upd_room(inter.guild_id, self.vc_id, locked=True)
        await self._reply(inter, "🔒 Room **locked** — no one new can join.")

    @discord.ui.button(emoji="🔓", style=discord.ButtonStyle.secondary, custom_id="vc_unlock_0", row=0)
    async def btn_unlock(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        ow = vc.overwrites_for(inter.guild.default_role)
        ow.connect = None
        await vc.set_permissions(inter.guild.default_role, overwrite=ow)
        upd_room(inter.guild_id, self.vc_id, locked=False)
        await self._reply(inter, "🔓 Room **unlocked** — anyone can join.")

    @discord.ui.button(emoji="🙈", style=discord.ButtonStyle.secondary, custom_id="vc_hide_0",   row=0)
    async def btn_hide(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        ow = vc.overwrites_for(inter.guild.default_role)
        ow.view_channel = False
        await vc.set_permissions(inter.guild.default_role, overwrite=ow)
        upd_room(inter.guild_id, self.vc_id, hidden=True)
        await self._reply(inter, "🙈 Room **hidden** from everyone.")

    @discord.ui.button(emoji="👁️", style=discord.ButtonStyle.secondary, custom_id="vc_show_0",   row=0)
    async def btn_show(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        ow = vc.overwrites_for(inter.guild.default_role)
        ow.view_channel = None
        await vc.set_permissions(inter.guild.default_role, overwrite=ow)
        upd_room(inter.guild_id, self.vc_id, hidden=False)
        await self._reply(inter, "👁️ Room **visible** again.")

    # ── Row 2 ─────────────────────────────────────────────────────────────────
    @discord.ui.button(emoji="👥", style=discord.ButtonStyle.secondary, custom_id="vc_limit_0",  row=1)
    async def btn_limit(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        async def cb(inter2, val):
            try:
                n = int(val)
                if not 0 <= n <= 99: raise ValueError
            except ValueError:
                await inter2.response.send_message("❌ Enter 0–99.", ephemeral=True); return
            await vc.edit(user_limit=n)
            await inter2.response.send_message(f"👥 Limit set to **{'Unlimited' if n==0 else n}**.", ephemeral=True)
        await inter.response.send_modal(_TextModal("👥 Set Limit", "Max members (0=unlimited)", "0–99", cb))

    @discord.ui.button(emoji="🤝", style=discord.ButtonStyle.secondary, custom_id="vc_invite_0", row=1)
    async def btn_invite(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        async def cb(inter2, uid):
            m = inter2.guild.get_member(uid)
            if not m: await inter2.response.send_message("❌ Member not found.", ephemeral=True); return
            ow = vc.overwrites_for(m)
            ow.connect = True; ow.view_channel = True
            await vc.set_permissions(m, overwrite=ow)
            banned = rd.get("banned", [])
            if uid in banned: banned.remove(uid)
            permitted = rd.get("permitted", []); permitted.append(uid)
            upd_room(inter2.guild_id, self.vc_id, permitted=list(set(permitted)), banned=banned)
            await inter2.response.send_message(f"🤝 **{m.display_name}** invited.", ephemeral=True)
        await inter.response.send_modal(_IDModal("🤝 Invite Member", cb))

    @discord.ui.button(emoji="🔨", style=discord.ButtonStyle.danger,     custom_id="vc_ban_0",   row=1)
    async def btn_ban(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        async def cb(inter2, uid):
            m = inter2.guild.get_member(uid)
            if not m: await inter2.response.send_message("❌ Member not found.", ephemeral=True); return
            if uid == rd["owner_id"]: await inter2.response.send_message("❌ Can't ban the owner.", ephemeral=True); return
            ow = vc.overwrites_for(m)
            ow.connect = False; ow.view_channel = False
            await vc.set_permissions(m, overwrite=ow)
            if m.voice and m.voice.channel == vc:
                await m.move_to(None)
            banned = rd.get("banned", []); banned.append(uid)
            upd_room(inter2.guild_id, self.vc_id, banned=list(set(banned)))
            await inter2.response.send_message(f"🔨 **{m.display_name}** banned from room.", ephemeral=True)
        await inter.response.send_modal(_IDModal("🔨 Ban Member", cb))

    @discord.ui.button(emoji="✅", style=discord.ButtonStyle.success,    custom_id="vc_permit_0", row=1)
    async def btn_permit(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        async def cb(inter2, uid):
            m = inter2.guild.get_member(uid)
            if not m: await inter2.response.send_message("❌ Member not found.", ephemeral=True); return
            ow = vc.overwrites_for(m)
            ow.connect = True
            await vc.set_permissions(m, overwrite=ow)
            await inter2.response.send_message(f"✅ **{m.display_name}** permitted.", ephemeral=True)
        await inter.response.send_modal(_IDModal("✅ Permit Member", cb))

    # ── Row 3 ─────────────────────────────────────────────────────────────────
    @discord.ui.button(emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="vc_rename_0",  row=2)
    async def btn_rename(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        async def cb(inter2, val):
            await vc.edit(name=val)
            await inter2.response.send_message(f"✏️ Room renamed to **{val}**.", ephemeral=True)
        await inter.response.send_modal(_TextModal("✏️ Rename Room", "New name", "e.g. 🎮 Gaming Night", cb))

    @discord.ui.button(emoji="🎧", style=discord.ButtonStyle.secondary, custom_id="vc_bitrate_0", row=2)
    async def btn_bitrate(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        async def cb(inter2, val):
            try:
                n = int(val)
                if not 8 <= n <= 384: raise ValueError
            except ValueError:
                await inter2.response.send_message("❌ Enter 8–384 kbps.", ephemeral=True); return
            await vc.edit(bitrate=n * 1000)
            await inter2.response.send_message(f"🎧 Bitrate set to **{n} kbps**.", ephemeral=True)
        await inter.response.send_modal(_TextModal("🎧 Set Bitrate", "Bitrate in kbps", "8–384 (default 64)", cb))

    @discord.ui.button(emoji="🌍", style=discord.ButtonStyle.secondary, custom_id="vc_region_0",  row=2)
    async def btn_region(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        regions = ["auto","brazil","europe","hongkong","india","japan",
                   "rotterdam","russia","singapore","southafrica","sydney","us-central",
                   "us-east","us-south","us-west"]
        select = discord.ui.Select(
            placeholder="Choose a region…",
            options=[discord.SelectOption(label=r.title(), value=r) for r in regions]
        )
        async def on_select(inter2: discord.Interaction):
            chosen = select.values[0]
            await vc.edit(rtc_region=None if chosen == "auto" else chosen)
            await inter2.response.send_message(f"🌍 Region set to **{chosen}**.", ephemeral=True)
        select.callback = on_select
        v = discord.ui.View(timeout=60); v.add_item(select)
        await inter.response.send_message("🌍 Choose a region:", view=v, ephemeral=True)

    @discord.ui.button(emoji="📋", style=discord.ButtonStyle.secondary, custom_id="vc_template_0", row=2)
    async def btn_template(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        templates = {
            "🎮 Gaming":      (0, 64000, False),
            "🎵 Music":       (0, 96000, False),
            "🔒 Private":     (4, 64000, True),
            "📢 Open Stage":  (0, 64000, False),
            "🎙️ Podcast":    (0, 64000, False),
        }
        select = discord.ui.Select(
            placeholder="Choose a template…",
            options=[discord.SelectOption(label=name, value=name) for name in templates]
        )
        async def on_select(inter2: discord.Interaction):
            name = select.values[0]
            limit, bitrate, lock = templates[name]
            await vc.edit(name=name, user_limit=limit, bitrate=bitrate)
            if lock:
                ow = vc.overwrites_for(inter2.guild.default_role)
                ow.connect = False
                await vc.set_permissions(inter2.guild.default_role, overwrite=ow)
                upd_room(inter2.guild_id, self.vc_id, locked=True)
            await inter2.response.send_message(f"📋 Template **{name}** applied.", ephemeral=True)
        select.callback = on_select
        v = discord.ui.View(timeout=60); v.add_item(select)
        await inter.response.send_message("📋 Choose a template:", view=v, ephemeral=True)

    # ── Row 4 ─────────────────────────────────────────────────────────────────
    @discord.ui.button(emoji="👑", style=discord.ButtonStyle.primary,  custom_id="vc_claim_0",    row=3)
    async def btn_claim(self, inter: discord.Interaction, _):
        rd = get_room(inter.guild_id, self.vc_id)
        if not rd: await inter.response.send_message("❌ Room not found.", ephemeral=True); return
        vc = inter.guild.get_channel(self.vc_id)
        if not vc: await inter.response.send_message("❌ VC gone.", ephemeral=True); return
        owner = inter.guild.get_member(rd["owner_id"])
        if owner and owner.voice and owner.voice.channel == vc:
            await inter.response.send_message("❌ The owner is still in the room.", ephemeral=True); return
        if inter.user.voice and inter.user.voice.channel == vc:
            upd_room(inter.guild_id, self.vc_id, owner_id=inter.user.id)
            await inter.response.send_message(f"👑 You are now the **room owner**.", ephemeral=True)
        else:
            await inter.response.send_message("❌ You must be in the room to claim it.", ephemeral=True)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.primary,  custom_id="vc_transfer_0", row=3)
    async def btn_transfer(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        async def cb(inter2, uid):
            m = inter2.guild.get_member(uid)
            if not m: await inter2.response.send_message("❌ Member not found.", ephemeral=True); return
            if not (m.voice and m.voice.channel == vc):
                await inter2.response.send_message("❌ That member isn't in your room.", ephemeral=True); return
            upd_room(inter2.guild_id, self.vc_id, owner_id=uid)
            await inter2.response.send_message(f"🔁 Room transferred to **{m.display_name}**.", ephemeral=True)
        await inter.response.send_modal(_IDModal("🔁 Transfer Ownership", cb))

    @discord.ui.button(emoji="⏳", style=discord.ButtonStyle.secondary, custom_id="vc_waiting_0", row=3)
    async def btn_waiting(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        # Toggle slow mode on the panel text channel as "waiting room" indicator
        panel_ch = inter.guild.get_channel(rd["panel_ch_id"])
        if panel_ch:
            slow = 0 if panel_ch.slowmode_delay > 0 else 5
            await panel_ch.edit(slowmode_delay=slow)
            status = "enabled ⏳" if slow else "disabled"
            await inter.response.send_message(f"⏳ Waiting mode **{status}**.", ephemeral=True)
        else:
            await inter.response.send_message("❌ Panel channel not found.", ephemeral=True)

    @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger,   custom_id="vc_del_0",     row=3)
    async def btn_delete(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        await inter.response.send_message("🗑️ Deleting your room…", ephemeral=True)
        # Delete VC
        try: await vc.delete(reason=f"Owner deleted | {inter.user}")
        except Exception: pass
        # Delete private panel text channel
        panel_ch = inter.guild.get_channel(rd["panel_ch_id"])
        if panel_ch:
            try: await panel_ch.delete(reason="Voice room closed")
            except Exception: pass
        del_room(inter.guild_id, self.vc_id)


# ─── Panel embed builder ──────────────────────────────────────────────────────

def _panel_embed(guild: discord.Guild, vc: discord.VoiceChannel, rd: dict) -> discord.Embed:
    owner = guild.get_member(rd["owner_id"])
    lock_icon  = "🔒 Locked"   if rd.get("locked") else "🔓 Open"
    hide_icon  = "🙈 Hidden"   if rd.get("hidden") else "👁️ Visible"
    members_in = [m.mention for m in vc.members] if vc else []

    embed = discord.Embed(
        title="🎙️ Voice Room Control Panel",
        description=(
            "Use these buttons to control your private voice room.\n"
            "You must have a room created by the system."
        ),
        color=0x5865F2,
        timestamp=datetime.now(),
    )
    embed.set_author(
        name=config.SERVER_NAME,
        icon_url=guild.icon.url if guild.icon else None,
    )
    if owner:
        embed.set_thumbnail(url=owner.display_avatar.url)
    embed.add_field(name="👑 Owner",   value=owner.mention if owner else "—",  inline=True)
    embed.add_field(name="🔒 Status",  value=lock_icon,                         inline=True)
    embed.add_field(name="👁️ Visible", value=hide_icon,                         inline=True)
    embed.add_field(
        name=f"🎤 Members ({len(members_in)})",
        value=" ".join(members_in) if members_in else "Empty",
        inline=False,
    )
    embed.set_footer(text=f"{config.BOT_NAME} | Channel ID: {vc.id if vc else '—'} | Dev: {config.DEVELOPER}")
    return embed


# ─── VoicePanelGroup (slash commands) ────────────────────────────────────────

class VoicePanelGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(
            name="voicepanel",
            description="🎙️ Voice room system",
            default_permissions=discord.Permissions(administrator=True),
        )
        self.bot = bot

    @app_commands.command(name="setup", description="⚙️ Set up the Join-to-Create voice system")
    @app_commands.describe(
        category       = "Category to create/use for voice rooms",
        default_name   = "Default room name — use {user} as placeholder",
        default_limit  = "Default user limit (0 = unlimited)",
    )
    async def setup(
        self,
        interaction: discord.Interaction,
        category:      discord.CategoryChannel,
        default_name:  str = "🎙️ {user}'s Room",
        default_limit: app_commands.Range[int, 0, 99] = 0,
    ):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild

        # ── 1. create the public text channel for the panel ──
        panel_overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True),
        }
        try:
            panel_text_ch = await guild.create_text_channel(
                name="📋・voice-panel",
                category=category,
                overwrites=panel_overwrites,
                topic="Manage your voice room using the buttons below.",
                reason="VoicePanel setup",
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Could not create panel channel: {e}", ephemeral=True); return

        # ── 2. create the Join-to-Create VC ──
        vc_overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True),
            guild.me:           discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, move_members=True),
        }
        try:
            jtc_vc = await guild.create_voice_channel(
                name="➕ Create Voice",
                category=category,
                user_limit=0,
                overwrites=vc_overwrites,
                reason="VoicePanel JTC setup",
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Could not create JTC channel: {e}", ephemeral=True); return

        # ── 3. post the panel embed in the text channel ──
        panel_embed = discord.Embed(
            title="🎙️ Voice Room System",
            description=(
                "Join **➕ Create Voice** to instantly get your own\n"
                "**private voice room** with full control.\n\n"
                "**What you can do in your room:**\n"
                "` 🔒 ` Lock / Unlock access\n"
                "` 🙈 ` Hide / Show your room\n"
                "` 👥 ` Set a member limit\n"
                "` 🤝 ` Invite specific members\n"
                "` 🔨 ` Ban / kick members\n"
                "` ✏️ ` Rename anytime\n"
                "` 👑 ` Claim or transfer ownership\n\n"
                "Your room is **deleted automatically** when empty."
            ),
            color=0x5865F2,
            timestamp=datetime.now(),
        )
        panel_embed.set_author(
            name=config.SERVER_NAME,
            icon_url=guild.icon.url if guild.icon else None,
        )
        panel_embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await panel_text_ch.send(embed=panel_embed)

        # ── 4. Save config ──
        set_cfg(interaction.guild_id, {
            "jtc_vc_id":      jtc_vc.id,
            "category_id":    category.id,
            "panel_text_id":  panel_text_ch.id,
            "default_name":   default_name,
            "default_limit":  default_limit,
            "rooms":          {},
        })

        confirm = discord.Embed(title="✅ Voice Panel Ready!", color=0x57F287)
        confirm.add_field(name="📋 Panel Channel", value=panel_text_ch.mention, inline=True)
        confirm.add_field(name="🔊 JTC Channel",   value=jtc_vc.mention,        inline=True)
        confirm.add_field(name="📁 Category",      value=category.name,         inline=True)
        confirm.add_field(name="👤 Default Name",  value=f"`{default_name}`",   inline=True)
        confirm.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.followup.send(embed=confirm, ephemeral=True)

    @app_commands.command(name="info", description="📊 Show voice panel config and active rooms")
    async def info(self, interaction: discord.Interaction):
        cfg = get_cfg(interaction.guild_id)
        if not cfg:
            await interaction.response.send_message("❌ Voice panel not configured.", ephemeral=True); return
        jtc    = interaction.guild.get_channel(cfg.get("jtc_vc_id",     0))
        txt    = interaction.guild.get_channel(cfg.get("panel_text_id", 0))
        cat    = interaction.guild.get_channel(cfg.get("category_id",   0))
        rooms  = all_rooms(interaction.guild_id)
        active = sum(1 for vid in rooms if interaction.guild.get_channel(int(vid)))
        embed = discord.Embed(title="🎙️ Voice Panel — Info", color=0x5865F2)
        embed.add_field(name="📋 Panel",     value=txt.mention  if txt  else "❌", inline=True)
        embed.add_field(name="🔊 JTC VC",    value=jtc.mention  if jtc  else "❌", inline=True)
        embed.add_field(name="📁 Category",  value=cat.name     if cat  else "❌", inline=True)
        embed.add_field(name="👤 Def. Name", value=f"`{cfg.get('default_name','—')}`", inline=True)
        embed.add_field(name="🎙️ Active",   value=str(active), inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="remove", description="🗑️ Disable the voice panel system")
    async def remove(self, interaction: discord.Interaction):
        d = _load(); d.pop(str(interaction.guild_id), None); _save(d)
        await interaction.response.send_message("✅ Voice panel system disabled.", ephemeral=True)


# ─── Cog ─────────────────────────────────────────────────────────────────────

class CreateVoice(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._group = VoicePanelGroup(bot)
        bot.tree.add_command(self._group)

    async def cog_unload(self):
        self.bot.tree.remove_command("voicepanel")

    # ── Join-to-Create listener ───────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after:  discord.VoiceState,
    ):
        cfg = get_cfg(member.guild.id)
        if not cfg:
            return

        jtc_id = cfg.get("jtc_vc_id")

        # ── Member joined the JTC channel ────────────────────────────────────
        if after.channel and after.channel.id == jtc_id:
            await self._create_room(member, cfg)

        # ── Member left a managed room — check if empty ───────────────────────
        if before.channel and before.channel.id != jtc_id:
            rd = get_room(member.guild.id, before.channel.id)
            if rd and len(before.channel.members) == 0:
                await asyncio.sleep(3)
                vc = member.guild.get_channel(before.channel.id)
                if vc and len(vc.members) == 0:
                    await self._destroy_room(member.guild, before.channel.id, rd)

    async def _create_room(self, member: discord.Member, cfg: dict):
        guild = member.guild
        cat   = guild.get_channel(cfg.get("category_id"))

        # One room per member
        rooms = all_rooms(guild.id)
        for vid, rd in rooms.items():
            if rd["owner_id"] == member.id and guild.get_channel(int(vid)):
                try:
                    await member.move_to(guild.get_channel(int(vid)))
                except Exception:
                    pass
                return

        name          = cfg.get("default_name", "🎙️ {user}'s Room").replace("{user}", member.display_name)
        default_limit = cfg.get("default_limit", 0)

        # ── Create the voice channel ──
        vc_ow = {
            guild.default_role: discord.PermissionOverwrite(connect=True, view_channel=True),
            member:             discord.PermissionOverwrite(connect=True, view_channel=True, manage_channels=True, move_members=True),
            guild.me:           discord.PermissionOverwrite(connect=True, view_channel=True, manage_channels=True, move_members=True),
        }
        try:
            vc = await guild.create_voice_channel(
                name=name, category=cat, user_limit=default_limit,
                overwrites=vc_ow, reason=f"Temp VC for {member}"
            )
        except Exception as e:
            print(f"[CreateVoice] VC create failed: {e}"); return

        # Move member in
        try:
            await member.move_to(vc)
        except Exception:
            pass

        # ── Create the private panel text channel ──
        txt_ow = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member:             discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True),
            guild.me:           discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        try:
            panel_ch = await guild.create_text_channel(
                name=f"📋・panel・room",
                category=cat,
                overwrites=txt_ow,
                reason=f"Private panel for {member}",
            )
        except Exception as e:
            print(f"[CreateVoice] Panel channel create failed: {e}")
            panel_ch = None

        # Seed room data (panel_ch_id=0 fallback if creation failed)
        rd_seed = {"owner_id": member.id, "locked": False, "hidden": False, "banned": [], "permitted": [],
                   "panel_ch_id": panel_ch.id if panel_ch else 0, "panel_msg_id": 0}
        add_room(guild.id, vc.id, member.id, panel_ch.id if panel_ch else 0, 0)

        if panel_ch:
            view  = VoiceControlView(vc_id=vc.id, owner_id=member.id, guild_id=guild.id)
            embed = _panel_embed(guild, vc, rd_seed)
            try:
                msg = await panel_ch.send(
                    content=member.mention,
                    embed=embed,
                    view=view,
                )
                upd_room(guild.id, vc.id, panel_msg_id=msg.id)
            except Exception as e:
                print(f"[CreateVoice] Panel msg failed: {e}")

    async def _destroy_room(self, guild: discord.Guild, vc_id: int, rd: dict):
        vc = guild.get_channel(vc_id)
        if vc:
            try: await vc.delete(reason="Temp VC: empty, auto-deleted")
            except Exception: pass
        panel_ch = guild.get_channel(rd.get("panel_ch_id", 0))
        if panel_ch:
            try: await panel_ch.delete(reason="Voice room closed")
            except Exception: pass
        del_room(guild.id, vc_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(CreateVoice(bot))
