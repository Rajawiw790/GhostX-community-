"""
Create Voice System — Ghostx Community
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Architecture (matches the screenshots):

  Category: Voice Rooms
  ├── #voice-panel             ← text channel with the public "Join to Create" embed
  │                              AND a permanent Controls legend (posted once at setup,
  │                              stays there always — no need to create a room to see it)
  └── ➕ Create Voice          ← join-to-create VC (permanent — bot recreates if deleted)

  When member joins ➕ Create Voice:
  ├── {name}'s Room             ← temp voice channel (auto-deleted when empty)
  └── panel • room (private)    ← private text channel, visible ONLY to the owner.
                                   The control panel + the same Controls legend are
                                   posted immediately — there is no delay.

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

# ─── Custom emojis (Ghostx application emojis) ──────────────────────────────
# Centralized here so every embed/button in this file pulls from the same
# source — change an ID once and it updates everywhere.
EMOJI = {
    "voice":    "<:15830voicechannelgreenalt:1530119939153989773>",
    "owner":    "<:fl_owner:1528968920118329445>",
    "members":  "<:19492membres:1530119986104897657>",
    "lock":     "<:fl_locked:1528968912266596442>",
    "unlock":   "<:9068ouvert:1530119863555854437>",
    "hide":     "<:fl_forbidden:1528968907530965013>",
    "show":     "<:60226check:1530120112194195558>",
    "limit":    "<:19492membres:1530119986104897657>",
    "invite":   "<:20806partnerids:1530119991628795990>",
    "ban":      "<:fl_ban:1528968895812206723>",
    "permit":   "<:85722ajouter:1530120231010177198>",
    "rename":   "<:36438designer:1530120035002089492>",
    "bitrate":  "<:26295bolt:1530120002127138958>",
    "region":   "<:64005web:1530120128849645748>",
    "template": "<:62470logs:1530120119827566623>",
    "claim":    "<:fl_owner:1528968920118329445>",
    "transfer": "<:8997modernrefresh:1530119860732956813>",
    "waiting":  "<:fl_loading:1528968909913460841>",
    "delete":   "<:14385supprimer:1530119918660354139>",
}

# (key, label, description) — the single source of truth for the legend shown
# both on the public #voice-panel channel AND inside every room's own panel.
LEGEND = [
    ("lock",     "Lock",         "Stop new members from joining your room"),
    ("unlock",   "Unlock",       "Allow anyone to join again"),
    ("hide",     "Hide",         "Hide the room from the channel list"),
    ("show",     "Show",         "Make the room visible again"),
    ("limit",    "Limit",        "Set a maximum number of members"),
    ("invite",   "Invite",       "Give a specific member access by ID"),
    ("ban",      "Ban",          "Block a member from this room"),
    ("permit",   "Permit",       "Allow a specific member to connect"),
    ("rename",   "Rename",       "Change the room's name"),
    ("bitrate",  "Bitrate",      "Set the audio quality (8–384 kbps)"),
    ("region",   "Region",       "Choose a voice server region"),
    ("template", "Template",     "Apply a preset (name, limit, bitrate)"),
    ("claim",    "Claim",        "Become owner if the current owner has left"),
    ("transfer", "Transfer",     "Hand ownership to another member in the room"),
    ("waiting",  "Waiting Room", "Toggle slowmode on this panel channel"),
    ("delete",   "Delete",       "Close the room and remove its panel"),
]


def _legend_text() -> str:
    return "\n".join(f"{EMOJI[key]} **{label}** — {desc}" for key, label, desc in LEGEND)


def build_legend_embed() -> discord.Embed:
    """The always-visible reference embed. Post this ONCE in the public
    #voice-panel channel during /voicepanel setup, right next to the
    'Join to Create' embed — it stays there permanently, so members can read
    what every control does before they ever create a room."""
    embed = discord.Embed(
        title=f"{EMOJI['voice']} Voice Room Controls",
        description="Create a room from the channel below and you'll get a private panel with these controls:",
        color=0x5865F2,
    )
    embed.add_field(name="\u200b", value=_legend_text(), inline=False)
    embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
    return embed


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
            await interaction.response.send_message(f"{EMOJI['ban']} Invalid ID.", ephemeral=True); return
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
            await inter.response.send_message(f"{EMOJI['ban']} Room data not found.", ephemeral=True)
            return None, None
        if inter.user.id != rd["owner_id"] and not inter.user.guild_permissions.administrator:
            await inter.response.send_message(f"{EMOJI['ban']} Only the room owner can do this.", ephemeral=True)
            return None, None
        vc = inter.guild.get_channel(self.vc_id)
        if not vc:
            await inter.response.send_message(f"{EMOJI['ban']} Voice channel no longer exists.", ephemeral=True)
            return None, None
        return vc, rd

    async def _reply(self, inter, text):
        if inter.response.is_done():
            await inter.followup.send(text, ephemeral=True)
        else:
            await inter.response.send_message(text, ephemeral=True)

    # ── Row 1 ─────────────────────────────────────────────────────────────────
    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="vc_lock_0",   row=0)
    async def btn_lock(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        ow = vc.overwrites_for(inter.guild.default_role)
        ow.connect = False
        await vc.set_permissions(inter.guild.default_role, overwrite=ow)
        upd_room(inter.guild_id, self.vc_id, locked=True)
        await self._reply(inter, f"{EMOJI['lock']} Room **locked** — no one new can join.")

    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="vc_unlock_0", row=0)
    async def btn_unlock(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        ow = vc.overwrites_for(inter.guild.default_role)
        ow.connect = None
        await vc.set_permissions(inter.guild.default_role, overwrite=ow)
        upd_room(inter.guild_id, self.vc_id, locked=False)
        await self._reply(inter, f"{EMOJI['unlock']} Room **unlocked** — anyone can join.")

    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="vc_hide_0",   row=0)
    async def btn_hide(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        ow = vc.overwrites_for(inter.guild.default_role)
        ow.view_channel = False
        await vc.set_permissions(inter.guild.default_role, overwrite=ow)
        upd_room(inter.guild_id, self.vc_id, hidden=True)
        await self._reply(inter, f"{EMOJI['hide']} Room **hidden** from everyone.")

    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="vc_show_0",   row=0)
    async def btn_show(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        ow = vc.overwrites_for(inter.guild.default_role)
        ow.view_channel = None
        await vc.set_permissions(inter.guild.default_role, overwrite=ow)
        upd_room(inter.guild_id, self.vc_id, hidden=False)
        await self._reply(inter, f"{EMOJI['show']} Room **visible** again.")

    # ── Row 2 ─────────────────────────────────────────────────────────────────
    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="vc_limit_0",  row=1)
    async def btn_limit(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        async def cb(inter2, val):
            try:
                n = int(val)
                if not 0 <= n <= 99: raise ValueError
            except ValueError:
                await inter2.response.send_message(f"{EMOJI['ban']} Enter 0–99.", ephemeral=True); return
            await vc.edit(user_limit=n)
            await inter2.response.send_message(f"{EMOJI['limit']} Limit set to **{'Unlimited' if n==0 else n}**.", ephemeral=True)
        await inter.response.send_modal(_TextModal("Set Limit", "Max members (0=unlimited)", "0–99", cb))

    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="vc_invite_0", row=1)
    async def btn_invite(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        async def cb(inter2, uid):
            m = inter2.guild.get_member(uid)
            if not m: await inter2.response.send_message(f"{EMOJI['ban']} Member not found.", ephemeral=True); return
            ow = vc.overwrites_for(m)
            ow.connect = True; ow.view_channel = True
            await vc.set_permissions(m, overwrite=ow)
            banned = rd.get("banned", [])
            if uid in banned: banned.remove(uid)
            permitted = rd.get("permitted", []); permitted.append(uid)
            upd_room(inter2.guild_id, self.vc_id, permitted=list(set(permitted)), banned=banned)
            await inter2.response.send_message(f"{EMOJI['invite']} **{m.display_name}** invited.", ephemeral=True)
        await inter.response.send_modal(_IDModal("Invite Member", cb))

    @discord.ui.button(style=discord.ButtonStyle.danger,     custom_id="vc_ban_0",   row=1)
    async def btn_ban(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        async def cb(inter2, uid):
            m = inter2.guild.get_member(uid)
            if not m: await inter2.response.send_message(f"{EMOJI['ban']} Member not found.", ephemeral=True); return
            if uid == rd["owner_id"]: await inter2.response.send_message(f"{EMOJI['ban']} Can't ban the owner.", ephemeral=True); return
            ow = vc.overwrites_for(m)
            ow.connect = False; ow.view_channel = False
            await vc.set_permissions(m, overwrite=ow)
            if m.voice and m.voice.channel == vc:
                await m.move_to(None)
            banned = rd.get("banned", []); banned.append(uid)
            upd_room(inter2.guild_id, self.vc_id, banned=list(set(banned)))
            await inter2.response.send_message(f"{EMOJI['ban']} **{m.display_name}** banned from room.", ephemeral=True)
        await inter.response.send_modal(_IDModal("Ban Member", cb))

    @discord.ui.button(style=discord.ButtonStyle.success,    custom_id="vc_permit_0", row=1)
    async def btn_permit(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        async def cb(inter2, uid):
            m = inter2.guild.get_member(uid)
            if not m: await inter2.response.send_message(f"{EMOJI['ban']} Member not found.", ephemeral=True); return
            ow = vc.overwrites_for(m)
            ow.connect = True
            await vc.set_permissions(m, overwrite=ow)
            await inter2.response.send_message(f"{EMOJI['permit']} **{m.display_name}** permitted.", ephemeral=True)
        await inter.response.send_modal(_IDModal("Permit Member", cb))

    # ── Row 3 ─────────────────────────────────────────────────────────────────
    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="vc_rename_0",  row=2)
    async def btn_rename(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        async def cb(inter2, val):
            await vc.edit(name=val)
            await inter2.response.send_message(f"{EMOJI['rename']} Room renamed to **{val}**.", ephemeral=True)
        await inter.response.send_modal(_TextModal("Rename Room", "New name", "e.g. Gaming Night", cb))

    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="vc_bitrate_0", row=2)
    async def btn_bitrate(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        async def cb(inter2, val):
            try:
                n = int(val)
                if not 8 <= n <= 384: raise ValueError
            except ValueError:
                await inter2.response.send_message(f"{EMOJI['ban']} Enter 8–384 kbps.", ephemeral=True); return
            await vc.edit(bitrate=n * 1000)
            await inter2.response.send_message(f"{EMOJI['bitrate']} Bitrate set to **{n} kbps**.", ephemeral=True)
        await inter.response.send_modal(_TextModal("Set Bitrate", "Bitrate in kbps", "8–384 (default 64)", cb))

    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="vc_region_0",  row=2)
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
            await inter2.response.send_message(f"{EMOJI['region']} Region set to **{chosen}**.", ephemeral=True)
        select.callback = on_select
        v = discord.ui.View(timeout=60); v.add_item(select)
        await inter.response.send_message(f"{EMOJI['region']} Choose a region:", view=v, ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="vc_template_0", row=2)
    async def btn_template(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        templates = {
            "Gaming":     (0, 64000, False),
            "Music":      (0, 96000, False),
            "Private":    (4, 64000, True),
            "Open Stage": (0, 64000, False),
            "Podcast":    (0, 64000, False),
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
            await inter2.response.send_message(f"{EMOJI['template']} Template **{name}** applied.", ephemeral=True)
        select.callback = on_select
        v = discord.ui.View(timeout=60); v.add_item(select)
        await inter.response.send_message(f"{EMOJI['template']} Choose a template:", view=v, ephemeral=True)

    # ── Row 4 ─────────────────────────────────────────────────────────────────
    @discord.ui.button(style=discord.ButtonStyle.primary,  custom_id="vc_claim_0",    row=3)
    async def btn_claim(self, inter: discord.Interaction, _):
        rd = get_room(inter.guild_id, self.vc_id)
        if not rd: await inter.response.send_message(f"{EMOJI['ban']} Room not found.", ephemeral=True); return
        vc = inter.guild.get_channel(self.vc_id)
        if not vc: await inter.response.send_message(f"{EMOJI['ban']} VC gone.", ephemeral=True); return
        owner = inter.guild.get_member(rd["owner_id"])
        if owner and owner.voice and owner.voice.channel == vc:
            await inter.response.send_message(f"{EMOJI['ban']} The owner is still in the room.", ephemeral=True); return
        if inter.user.voice and inter.user.voice.channel == vc:
            upd_room(inter.guild_id, self.vc_id, owner_id=inter.user.id)
            await inter.response.send_message(f"{EMOJI['claim']} You are now the **room owner**.", ephemeral=True)
        else:
            await inter.response.send_message(f"{EMOJI['ban']} You must be in the room to claim it.", ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.primary,  custom_id="vc_transfer_0", row=3)
    async def btn_transfer(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        async def cb(inter2, uid):
            m = inter2.guild.get_member(uid)
            if not m: await inter2.response.send_message(f"{EMOJI['ban']} Member not found.", ephemeral=True); return
            if not (m.voice and m.voice.channel == vc):
                await inter2.response.send_message(f"{EMOJI['ban']} That member isn't in your room.", ephemeral=True); return
            upd_room(inter2.guild_id, self.vc_id, owner_id=uid)
            await inter2.response.send_message(f"{EMOJI['transfer']} Room transferred to **{m.display_name}**.", ephemeral=True)
        await inter.response.send_modal(_IDModal("Transfer Ownership", cb))

    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="vc_waiting_0", row=3)
    async def btn_waiting(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        panel_ch = inter.guild.get_channel(rd["panel_ch_id"])
        if panel_ch:
            slow = 0 if panel_ch.slowmode_delay > 0 else 5
            await panel_ch.edit(slowmode_delay=slow)
            status = "enabled" if slow else "disabled"
            await inter.response.send_message(f"{EMOJI['waiting']} Waiting mode **{status}**.", ephemeral=True)
        else:
            await inter.response.send_message(f"{EMOJI['ban']} Panel channel not found.", ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.danger,   custom_id="vc_del_0",     row=3)
    async def btn_delete(self, inter: discord.Interaction, _):
        vc, rd = await self._auth(inter)
        if not vc: return
        await inter.response.send_message(f"{EMOJI['delete']} Deleting your room…", ephemeral=True)
        try: await vc.delete(reason=f"Owner deleted | {inter.user}")
        except Exception: pass
        panel_ch = inter.guild.get_channel(rd["panel_ch_id"])
        if panel_ch:
            try: await panel_ch.delete(reason="Voice room closed")
            except Exception: pass
        del_room(inter.guild_id, self.vc_id)


# ─── Panel embed builder ──────────────────────────────────────────────────────

def _panel_embed(guild: discord.Guild, vc: discord.VoiceChannel, rd: dict) -> discord.Embed:
    owner = guild.get_member(rd["owner_id"])
    lock_icon  = f"{EMOJI['lock']} Locked"  if rd.get("locked") else f"{EMOJI['unlock']} Open"
    hide_icon  = f"{EMOJI['hide']} Hidden"  if rd.get("hidden") else f"{EMOJI['show']} Visible"
    members_in = [m.mention for m in vc.members] if vc else []

    embed = discord.Embed(
        title=f"{EMOJI['voice']} Voice Room Control Panel",
        description="This panel is posted immediately when your room is created and stays here for as long as it exists.",
        color=0x5865F2,
        timestamp=datetime.now(),
    )
    embed.set_author(
        name=config.SERVER_NAME,
        icon_url=guild.icon.url if guild.icon else None,
    )
    if owner:
        embed.set_thumbnail(url=owner.display_avatar.url)
    embed.add_field(name="Owner",   value=owner.mention if owner else "—", inline=True)
    embed.add_field(name="Status",  value=lock_icon, inline=True)
    embed.add_field(name="Visibility", value=hide_icon, inline=True)
    embed.add_field(
        name=f"{EMOJI['members']} Members ({len(members_in)})",
        value=" ".join(members_in) if members_in else "Empty",
        inline=False,
    )
    embed.add_field(name="Controls", value=_legend_text(), inline=False)
    embed.set_footer(text=f"{config.BOT_NAME} | Channel ID: {vc.id if vc else '—'} | Dev: {config.DEVELOPER}")
    return embed


# ─── VoicePanelGroup (slash commands) ──────────────────────
# NOTE: this is where your file was cut off in the message you sent me —
# I don't have the /voicepanel setup / info / remove commands, so I can't
# edit them directly yet. Paste that part and I'll wire build_legend_embed()
# into the public #voice-panel channel for you (see instructions below).
