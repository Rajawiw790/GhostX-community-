"""
Create Voice System — Ghostx Community
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Architecture (v2 — single shared panel):

  Category: Voice Rooms
  ├── #voice-panel             ← text channel with ONE persistent embed + the
  │                              16-button control panel. Posted once by
  │                              /voicepanel setup and never duplicated —
  │                              re-running setup / customize edits this same
  │                              message in place.
  └── ➕ Create Voice          ← join-to-create VC (permanent — bot recreates
                                  it if deleted)

  When a member joins ➕ Create Voice:
  └── {name}'s Room             ← temp voice channel (auto-deleted when empty)

  There is NO private per-room text channel anymore. Every button on the
  shared #voice-panel message is dynamic: when a member clicks it, the bot
  looks at *that member's current voice channel* to figure out which room to
  act on. So the panel only ever needs to exist in one place, and it works
  the instant /voicepanel setup runs — no need to create a room first to see
  it, and no per-room panel channel to create/clean up.

  Note: Discord channel NAMES only support unicode emoji, not the custom
  application emojis below — so channel names keep plain unicode, while every
  embed/button uses the real Ghostx custom emojis.

Admin commands:
  /voicepanel setup      — creates the category + channels (or refreshes the
                            panel in place if already configured)
  /voicepanel customize   — edit the panel embed (title/description/image/
                            thumbnail/footer/color) without touching channels
  /voicepanel info        — show current config + active rooms
  /voicepanel remove      — disable and clean up
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
    "check":    "<:fl_check:1528968902837538846>",
    "category": "<:64005web:1530120128849645748>",
    "panel":    "<:62470logs:1530120119827566623>",
}

DEFAULT_PANEL_COLOR = 0x5865F2


# ─── Storage ─────────────────────────────────────────────────────────────────

def _load() -> dict:
    return db.load(VOICE_COLLECTION)

def _save(data: dict):
    db.save(VOICE_COLLECTION, data)

def get_cfg(guild_id: int) -> dict:
    return _load().get(str(guild_id), {})

def set_cfg(guild_id: int, cfg: dict):
    d = _load(); d[str(guild_id)] = cfg; _save(d)

def add_room(guild_id: int, vc_id: int, owner_id: int):
    d = _load()
    d.setdefault(str(guild_id), {}).setdefault("rooms", {})[str(vc_id)] = {
        "owner_id": owner_id,
        "locked":   False,
        "hidden":   False,
        "banned":   [],
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

def find_room_by_owner(guild_id: int, owner_id: int):
    """Returns (vc_id, room_dict) for the room this member owns, or (None, None)."""
    for vid, rd in all_rooms(guild_id).items():
        if rd.get("owner_id") == owner_id:
            return int(vid), rd
    return None, None


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


# ─── Shared Control Panel View (16 buttons, 4 rows) ──────────────────────────

class VoiceControlView(discord.ui.View):
    """
    ONE persistent view, posted ONCE on the shared #voice-panel message.
    custom_ids are static (no per-room suffix) because this view isn't tied
    to any single room — every button figures out "which room" by looking
    at the clicking member's current voice channel. This is what lets a
    single message control everyone's room without a private panel per
    person.
    """
    def __init__(self):
        super().__init__(timeout=None)

    # ── helpers ──────────────────────────────────────────────────────────────
    async def _target(self, inter: discord.Interaction, require_owner: bool = True):
        """Resolve (voice_channel, room_dict) for the button click, based on
        the clicking member's current voice channel — NOT any stored vc_id,
        since this view is shared by everyone."""
        vs = inter.user.voice
        if not vs or not vs.channel:
            await inter.response.send_message(
                f"{EMOJI['ban']} You need to be connected to your voice room to use this.",
                ephemeral=True,
            )
            return None, None
        vc = vs.channel
        rd = get_room(inter.guild_id, vc.id)
        if not rd:
            await inter.response.send_message(
                f"{EMOJI['ban']} This voice channel isn't a managed room.",
                ephemeral=True,
            )
            return None, None
        if require_owner and inter.user.id != rd["owner_id"] and not inter.user.guild_permissions.administrator:
            await inter.response.send_message(
                f"{EMOJI['ban']} Only the room owner can do that.",
                ephemeral=True,
            )
            return None, None
        return vc, rd

    async def _reply(self, inter, text):
        if inter.response.is_done():
            await inter.followup.send(text, ephemeral=True)
        else:
            await inter.response.send_message(text, ephemeral=True)

    @staticmethod
    async def _swap_owner(guild: discord.Guild, vc: discord.VoiceChannel,
                           old_owner_id: int, new_owner: discord.Member):
        """Move the VC's elevated Discord permission overwrite from the old
        owner to the new owner. Without this, claim/transfer only updated the
        DB and the new owner had no real manage_channels/move_members access."""
        old_owner = guild.get_member(old_owner_id)
        if old_owner and old_owner.id != new_owner.id:
            try:
                await vc.set_permissions(old_owner, overwrite=None)
            except Exception:
                pass
        try:
            await vc.set_permissions(
                new_owner,
                connect=True, view_channel=True,
                manage_channels=True, move_members=True,
            )
        except Exception:
            pass

    # ── Row 1 ─────────────────────────────────────────────────────────────────
    @discord.ui.button(emoji=EMOJI["lock"], style=discord.ButtonStyle.secondary, custom_id="vc_lock", row=0)
    async def btn_lock(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter)
        if not vc: return
        ow = vc.overwrites_for(inter.guild.default_role)
        ow.connect = False
        await vc.set_permissions(inter.guild.default_role, overwrite=ow)
        upd_room(inter.guild_id, vc.id, locked=True)
        await self._reply(inter, f"{EMOJI['lock']} Room **locked** — no one new can join.")

    @discord.ui.button(emoji=EMOJI["unlock"], style=discord.ButtonStyle.secondary, custom_id="vc_unlock", row=0)
    async def btn_unlock(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter)
        if not vc: return
        ow = vc.overwrites_for(inter.guild.default_role)
        ow.connect = None
        await vc.set_permissions(inter.guild.default_role, overwrite=ow)
        upd_room(inter.guild_id, vc.id, locked=False)
        await self._reply(inter, f"{EMOJI['unlock']} Room **unlocked** — anyone can join.")

    @discord.ui.button(emoji=EMOJI["hide"], style=discord.ButtonStyle.secondary, custom_id="vc_hide", row=0)
    async def btn_hide(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter)
        if not vc: return
        ow = vc.overwrites_for(inter.guild.default_role)
        ow.view_channel = False
        await vc.set_permissions(inter.guild.default_role, overwrite=ow)
        upd_room(inter.guild_id, vc.id, hidden=True)
        await self._reply(inter, f"{EMOJI['hide']} Room **hidden** from everyone.")

    @discord.ui.button(emoji=EMOJI["show"], style=discord.ButtonStyle.secondary, custom_id="vc_show", row=0)
    async def btn_show(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter)
        if not vc: return
        ow = vc.overwrites_for(inter.guild.default_role)
        ow.view_channel = None
        await vc.set_permissions(inter.guild.default_role, overwrite=ow)
        upd_room(inter.guild_id, vc.id, hidden=False)
        await self._reply(inter, f"{EMOJI['show']} Room **visible** again.")

    # ── Row 2 ─────────────────────────────────────────────────────────────────
    @discord.ui.button(emoji=EMOJI["limit"], style=discord.ButtonStyle.secondary, custom_id="vc_limit", row=1)
    async def btn_limit(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter)
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

    @discord.ui.button(emoji=EMOJI["invite"], style=discord.ButtonStyle.secondary, custom_id="vc_invite", row=1)
    async def btn_invite(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter)
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
            upd_room(inter2.guild_id, vc.id, permitted=list(set(permitted)), banned=banned)
            await inter2.response.send_message(f"{EMOJI['invite']} **{m.display_name}** invited.", ephemeral=True)
        await inter.response.send_modal(_IDModal("Invite Member", cb))

    @discord.ui.button(emoji=EMOJI["ban"], style=discord.ButtonStyle.secondary, custom_id="vc_ban", row=1)
    async def btn_ban(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter)
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
            upd_room(inter2.guild_id, vc.id, banned=list(set(banned)))
            await inter2.response.send_message(f"{EMOJI['ban']} **{m.display_name}** banned from room.", ephemeral=True)
        await inter.response.send_modal(_IDModal("Ban Member", cb))

    @discord.ui.button(emoji=EMOJI["permit"], style=discord.ButtonStyle.secondary, custom_id="vc_permit", row=1)
    async def btn_permit(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter)
        if not vc: return
        async def cb(inter2, uid):
            m = inter2.guild.get_member(uid)
            if not m: await inter2.response.send_message(f"{EMOJI['ban']} Member not found.", ephemeral=True); return
            ow = vc.overwrites_for(m)
            ow.connect = True
            await vc.set_permissions(m, overwrite=ow)
            permitted = rd.get("permitted", []); permitted.append(uid)
            upd_room(inter2.guild_id, vc.id, permitted=list(set(permitted)))
            await inter2.response.send_message(f"{EMOJI['permit']} **{m.display_name}** permitted.", ephemeral=True)
        await inter.response.send_modal(_IDModal("Permit Member", cb))

    # ── Row 3 ─────────────────────────────────────────────────────────────────
    @discord.ui.button(emoji=EMOJI["rename"], style=discord.ButtonStyle.secondary, custom_id="vc_rename", row=2)
    async def btn_rename(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter)
        if not vc: return
        async def cb(inter2, val):
            await vc.edit(name=val)
            await inter2.response.send_message(f"{EMOJI['rename']} Room renamed to **{val}**.", ephemeral=True)
        await inter.response.send_modal(_TextModal("Rename Room", "New name", "e.g. Gaming Night", cb))

    @discord.ui.button(emoji=EMOJI["bitrate"], style=discord.ButtonStyle.secondary, custom_id="vc_bitrate", row=2)
    async def btn_bitrate(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter)
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

    @discord.ui.button(emoji=EMOJI["region"], style=discord.ButtonStyle.secondary, custom_id="vc_region", row=2)
    async def btn_region(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter)
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

    @discord.ui.button(emoji=EMOJI["template"], style=discord.ButtonStyle.secondary, custom_id="vc_template", row=2)
    async def btn_template(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter)
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
                upd_room(inter2.guild_id, vc.id, locked=True)
            await inter2.response.send_message(f"{EMOJI['template']} Template **{name}** applied.", ephemeral=True)
        select.callback = on_select
        v = discord.ui.View(timeout=60); v.add_item(select)
        await inter.response.send_message(f"{EMOJI['template']} Choose a template:", view=v, ephemeral=True)

    # ── Row 4 ─────────────────────────────────────────────────────────────────
    @discord.ui.button(emoji=EMOJI["claim"], style=discord.ButtonStyle.secondary, custom_id="vc_claim", row=3)
    async def btn_claim(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter, require_owner=False)
        if not vc: return
        if rd["owner_id"] == inter.user.id:
            await inter.response.send_message(f"{EMOJI['ban']} You already own this room.", ephemeral=True); return
        owner = inter.guild.get_member(rd["owner_id"])
        if owner and owner.voice and owner.voice.channel == vc:
            await inter.response.send_message(f"{EMOJI['ban']} The current owner is still in the room.", ephemeral=True); return
        await self._swap_owner(inter.guild, vc, old_owner_id=rd["owner_id"], new_owner=inter.user)
        upd_room(inter.guild_id, vc.id, owner_id=inter.user.id)
        await inter.response.send_message(f"{EMOJI['claim']} You are now the **room owner**.", ephemeral=True)

    @discord.ui.button(emoji=EMOJI["transfer"], style=discord.ButtonStyle.secondary, custom_id="vc_transfer", row=3)
    async def btn_transfer(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter)
        if not vc: return
        async def cb(inter2, uid):
            m = inter2.guild.get_member(uid)
            if not m: await inter2.response.send_message(f"{EMOJI['ban']} Member not found.", ephemeral=True); return
            if not (m.voice and m.voice.channel == vc):
                await inter2.response.send_message(f"{EMOJI['ban']} That member isn't in your room.", ephemeral=True); return
            await self._swap_owner(inter2.guild, vc, old_owner_id=rd["owner_id"], new_owner=m)
            upd_room(inter2.guild_id, vc.id, owner_id=uid)
            await inter2.response.send_message(f"{EMOJI['transfer']} Room transferred to **{m.display_name}**.", ephemeral=True)
        await inter.response.send_modal(_IDModal("Transfer Ownership", cb))

    @discord.ui.button(emoji=EMOJI["waiting"], style=discord.ButtonStyle.secondary, custom_id="vc_waiting", row=3)
    async def btn_waiting(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter)
        if not vc: return
        # Voice channels have their own text-in-voice chat with slowmode —
        # reused here since there's no more private panel channel to
        # slowmode. Toggles a 5s slowmode on that in-voice chat.
        new_delay = 0 if getattr(vc, "slowmode_delay", 0) else 5
        await vc.edit(slowmode_delay=new_delay)
        status = "enabled" if new_delay else "disabled"
        await inter.response.send_message(f"{EMOJI['waiting']} Waiting mode **{status}**.", ephemeral=True)

    @discord.ui.button(emoji=EMOJI["delete"], style=discord.ButtonStyle.secondary, custom_id="vc_delete", row=3)
    async def btn_delete(self, inter: discord.Interaction, _):
        vc, rd = await self._target(inter)
        if not vc: return
        await inter.response.send_message(f"{EMOJI['delete']} Deleting your room…", ephemeral=True)
        try: await vc.delete(reason=f"Owner deleted | {inter.user}")
        except Exception: pass
        del_room(inter.guild_id, vc.id)


# ─── Shared panel embed builder (short, fully customizable) ─────────────────

def build_panel_embed(guild: discord.Guild, cfg: dict) -> discord.Embed:
    """Short embed for the single shared #voice-panel message. No verbose
    per-button legend anymore — buttons carry their own emoji + label, so
    the embed just needs a short intro. Every visual piece is customizable
    via /voicepanel setup or /voicepanel customize:
      panel_title, panel_desc, panel_image, panel_thumbnail,
      panel_footer, panel_color
    """
    jtc = guild.get_channel(cfg.get("jtc_vc_id", 0))
    jtc_mention = jtc.mention if jtc else "**Create Voice**"

    embed = discord.Embed(
        title=cfg.get("panel_title") or f"{EMOJI['voice']} Voice Rooms",
        description=cfg.get("panel_desc") or (
            f"Join {jtc_mention} to get your own room, then use the buttons "
            "below anytime to control it."
        ),
        color=cfg.get("panel_color", DEFAULT_PANEL_COLOR),
    )
    thumbnail = cfg.get("panel_thumbnail")
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    image = cfg.get("panel_image")
    if image:
        embed.set_image(url=image)
    embed.set_footer(text=cfg.get("panel_footer") or f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
    return embed


async def _refresh_panel_message(guild: discord.Guild, cfg: dict) -> discord.Message | None:
    """Edits the existing shared panel message in place if it still exists,
    otherwise sends a new one. Always keeps exactly ONE panel message per
    guild — never duplicates it."""
    panel_ch = guild.get_channel(cfg.get("panel_text_id", 0))
    if not panel_ch:
        return None

    embed = build_panel_embed(guild, cfg)
    view = VoiceControlView()

    msg_id = cfg.get("panel_msg_id")
    if msg_id:
        try:
            msg = await panel_ch.fetch_message(msg_id)
            return await msg.edit(embed=embed, view=view)
        except Exception:
            pass  # message was deleted or inaccessible — fall through and repost

    msg = await panel_ch.send(embed=embed, view=view)
    cfg["panel_msg_id"] = msg.id
    set_cfg(guild.id, cfg)
    return msg


# ─── VoicePanelGroup (slash commands) ────────────────────────────────────────

class VoicePanelGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(
            name="voicepanel",
            description="Voice room system",
            default_permissions=discord.Permissions(administrator=True),
        )
        self.bot = bot

    @app_commands.command(name="setup", description="Set up (or refresh) the Voice Rooms panel")
    @app_commands.describe(
        category      = "Category to create/use for voice rooms",
        default_name  = "Default room name — use {user} as placeholder",
        default_limit = "Default user limit (0 = unlimited)",
        title         = "Custom panel title (optional)",
        description   = "Custom panel description (optional, keep it short)",
        image         = "Image URL shown at the bottom of the panel (optional)",
        thumbnail     = "Thumbnail URL shown top-right of the panel (optional)",
        footer        = "Custom footer text (optional)",
        color         = "Hex color like 5865F2 (optional)",
    )
    async def setup(
        self,
        interaction: discord.Interaction,
        category:      discord.CategoryChannel,
        default_name:  str = "{user}'s Room",
        default_limit: app_commands.Range[int, 0, 99] = 0,
        title:         str = None,
        description:   str = None,
        image:         str = None,
        thumbnail:     str = None,
        footer:        str = None,
        color:         str = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        cfg = get_cfg(interaction.guild_id)

        existing_panel_ch = guild.get_channel(cfg.get("panel_text_id", 0)) if cfg else None
        existing_jtc      = guild.get_channel(cfg.get("jtc_vc_id", 0))     if cfg else None

        if cfg and existing_panel_ch and existing_jtc:
            # Already configured — reuse the existing channels, just refresh
            # config + the panel message in place (no duplicate channels/messages).
            panel_text_ch = existing_panel_ch
            jtc_vc        = existing_jtc
        else:
            # ── 1. create the public text channel for the panel ──
            panel_overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True),
            }
            try:
                panel_text_ch = await guild.create_text_channel(
                    name="voice-panel",
                    category=category,
                    overwrites=panel_overwrites,
                    topic="Manage your voice room using the buttons below.",
                    reason="VoicePanel setup",
                )
            except Exception as e:
                await interaction.followup.send(f"{EMOJI['ban']} Could not create panel channel: {e}", ephemeral=True); return

            # ── 2. create the Join-to-Create VC ──
            vc_overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True),
                guild.me:           discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, move_members=True),
            }
            try:
                jtc_vc = await guild.create_voice_channel(
                    name="Create Voice",
                    category=category,
                    user_limit=0,
                    overwrites=vc_overwrites,
                    reason="VoicePanel JTC setup",
                )
            except Exception as e:
                await interaction.followup.send(f"{EMOJI['ban']} Could not create JTC channel: {e}", ephemeral=True); return

        # ── 3. Save config FIRST, before touching any embeds ──
        # Config must exist before we try to post/edit anything cosmetic, so
        # a failure below can never leave channels created but unconfigured.
        cfg = get_cfg(interaction.guild_id) or {}
        cfg.update({
            "jtc_vc_id":      jtc_vc.id,
            "category_id":    category.id,
            "panel_text_id":  panel_text_ch.id,
            "default_name":   default_name,
            "default_limit":  default_limit,
            "rooms":          cfg.get("rooms", {}),
        })
        if title       is not None: cfg["panel_title"] = title
        if description is not None: cfg["panel_desc"] = description
        if image       is not None: cfg["panel_image"] = image
        if thumbnail   is not None: cfg["panel_thumbnail"] = thumbnail
        if footer      is not None: cfg["panel_footer"] = footer
        if color:
            try:
                cfg["panel_color"] = int(color.strip("#"), 16)
            except ValueError:
                pass
        set_cfg(interaction.guild_id, cfg)

        # ── 4. post (or refresh in place) the ONE shared panel message ──
        try:
            await _refresh_panel_message(guild, cfg)
        except Exception as e:
            await interaction.followup.send(
                f"{EMOJI['ban']} Setup finished and is active, but posting/updating the panel message failed: {e}",
                ephemeral=True,
            )
            return

        confirm = discord.Embed(title=f"{EMOJI['check']} Voice Panel Ready", color=0x57F287)
        confirm.add_field(name="Panel Channel", value=panel_text_ch.mention, inline=True)
        confirm.add_field(name="JTC Channel",   value=jtc_vc.mention,        inline=True)
        confirm.add_field(name="Category",      value=category.name,         inline=True)
        confirm.add_field(name="Default Name",  value=f"`{default_name}`",   inline=True)
        confirm.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.followup.send(embed=confirm, ephemeral=True)

    @app_commands.command(name="customize", description="Edit the panel embed without touching channels")
    @app_commands.describe(
        title       = "Custom panel title",
        description = "Custom panel description (keep it short)",
        image       = "Image URL shown at the bottom of the panel — pass 'none' to remove",
        thumbnail   = "Thumbnail URL shown top-right of the panel — pass 'none' to remove",
        footer      = "Custom footer text",
        color       = "Hex color like 5865F2",
    )
    async def customize(
        self,
        interaction: discord.Interaction,
        title:       str = None,
        description: str = None,
        image:       str = None,
        thumbnail:   str = None,
        footer:      str = None,
        color:       str = None,
    ):
        cfg = get_cfg(interaction.guild_id)
        guild = interaction.guild
        if not cfg or not guild.get_channel(cfg.get("panel_text_id", 0)):
            await interaction.response.send_message(
                f"{EMOJI['ban']} Run `/voicepanel setup` first.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        if title       is not None: cfg["panel_title"] = title
        if description is not None: cfg["panel_desc"] = description
        if image       is not None: cfg["panel_image"] = None if image.lower() == "none" else image
        if thumbnail   is not None: cfg["panel_thumbnail"] = None if thumbnail.lower() == "none" else thumbnail
        if footer      is not None: cfg["panel_footer"] = footer
        if color:
            try:
                cfg["panel_color"] = int(color.strip("#"), 16)
            except ValueError:
                await interaction.followup.send(f"{EMOJI['ban']} Invalid hex color.", ephemeral=True); return
        set_cfg(interaction.guild_id, cfg)

        try:
            await _refresh_panel_message(guild, cfg)
        except Exception as e:
            await interaction.followup.send(f"{EMOJI['ban']} Couldn't update the panel: {e}", ephemeral=True); return

        await interaction.followup.send(f"{EMOJI['check']} Panel updated.", ephemeral=True)

    @app_commands.command(name="info", description="Show voice panel config and active rooms")
    async def info(self, interaction: discord.Interaction):
        cfg = get_cfg(interaction.guild_id)
        if not cfg:
            await interaction.response.send_message(f"{EMOJI['ban']} Voice panel not configured.", ephemeral=True); return
        jtc    = interaction.guild.get_channel(cfg.get("jtc_vc_id",     0))
        txt    = interaction.guild.get_channel(cfg.get("panel_text_id", 0))
        cat    = interaction.guild.get_channel(cfg.get("category_id",   0))
        rooms  = all_rooms(interaction.guild_id)
        active = sum(1 for vid in rooms if interaction.guild.get_channel(int(vid)))
        embed = discord.Embed(title=f"{EMOJI['voice']} Voice Panel — Info", color=0x5865F2)
        embed.add_field(name="Panel",     value=txt.mention if txt else "—", inline=True)
        embed.add_field(name="JTC VC",    value=jtc.mention if jtc else "—", inline=True)
        embed.add_field(name="Category",  value=cat.name if cat else "—", inline=True)
        embed.add_field(name="Def. Name", value=f"`{cfg.get('default_name','—')}`", inline=True)
        embed.add_field(name="Active Rooms", value=str(active), inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="remove", description="Disable the voice panel system")
    async def remove(self, interaction: discord.Interaction):
        d = _load(); d.pop(str(interaction.guild_id), None); _save(d)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"{EMOJI['check']} Voice panel system disabled.", color=0x57F287),
            ephemeral=True,
        )


# ─── Cog ─────────────────────────────────────────────────────────────────────

class CreateVoice(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._group = VoicePanelGroup(bot)
        bot.tree.add_command(self._group)

    async def cog_load(self):
        # Register the shared control view as persistent so its buttons keep
        # working across bot restarts (static custom_ids + timeout=None).
        self.bot.add_view(VoiceControlView())

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
                    await self._destroy_room(member.guild, before.channel.id)

    async def _dm_error(self, member: discord.Member, text: str):
        """Errors here used to only go to the console (print). That made
        failures invisible to everyone except whoever reads Railway logs.
        Now we also DM the member so the failure is obvious immediately."""
        print(f"[CreateVoice] {text}")
        try:
            await member.send(f"{EMOJI['ban']} {text}")
        except Exception:
            pass  # member has DMs closed — the console log above is the fallback

    async def _create_room(self, member: discord.Member, cfg: dict):
        guild = member.guild
        cat   = guild.get_channel(cfg.get("category_id"))
        if not cat:
            await self._dm_error(member, "Voice panel category no longer exists — ask an admin to run /voicepanel setup again.")
            return

        # One room per member — if they already own a live room, just move
        # them back into it instead of creating a duplicate.
        existing_vc_id, rd = find_room_by_owner(guild.id, member.id)
        if existing_vc_id:
            existing_vc = guild.get_channel(existing_vc_id)
            if existing_vc:
                try:
                    await member.move_to(existing_vc)
                except Exception:
                    pass
                return
            else:
                del_room(guild.id, existing_vc_id)  # stale entry, clean it up

        name          = cfg.get("default_name", "{user}'s Room").replace("{user}", member.display_name)
        default_limit = cfg.get("default_limit", 0)

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
            await self._dm_error(
                member,
                f"Couldn't create your voice room ({e}). This is usually a missing "
                "'Manage Channels' permission for the bot in that category, or the "
                "category has hit Discord's 50-channel limit.",
            )
            return

        try:
            await member.move_to(vc)
        except Exception:
            pass

        add_room(guild.id, vc.id, member.id)

    async def _destroy_room(self, guild: discord.Guild, vc_id: int):
        vc = guild.get_channel(vc_id)
        if vc:
            try: await vc.delete(reason="Temp VC: empty, auto-deleted")
            except Exception: pass
        del_room(guild.id, vc_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(CreateVoice(bot))
