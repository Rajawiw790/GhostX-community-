"""
Resources System v2 — Ghostx Community
────────────────────────────────────────
نظام موارد كامل (سكريبتات SA-MP، مودات، أدوات، شيتات، سكريبتات بوتات...)
مبني على Category واحدة ثابتة اسمها RESOURCES فيها:

  📜-samp  🎨-mods  🛠️-tools  💀-cheats  🤖-bot-scripts  📂-other   ← رومات النشر
  📥-pending                                                        ← مراجعة الستاف
  📋-logs                                                           ← سجل القبول/الرفض

+ روم Panel منفصلة فيها زر واحد "📦 Publish Resource" (ستايل Components V2 —
  نفس القالب المستعمل فـ apply_system.py: Container بـ accent bar).

تدفق الاستخدام:
  1) Panel button → Dropdown (يختار التصنيف)
  2) Modal (عنوان + وصف مختصر + شرح كامل)
  3) البوت كيطلب من العضو (فـ الخاص، أو فـ نفس الروم إلا كانت الرسائل الخاصة
     مسدودة) يصيفط صورة و/أو ملف و/أو رابط تحميل — كلشي اختياري
  4) الطلب كيتبعت لـ #pending بـ Embed احترافي + أزرار:
     ✅ Approve   ❌ Reject   ✏️ Edit   🚫 Ban User
  5) عند القبول: كيتولد ID تلقائي (مثلاً SAMP-001) وكينشر الريسورس فـ الروم
     المخصصة لتصنيفو، وكيتسجل فـ #logs، وكيتوصل صاحبو برسالة فـ الخاص.

التخزين: MongoDB عبر db.py (نفس الطبقة لي كتستعملها باقي الكوجز فهاد المشروع) —
  • collection "resource_settings" → document واحد بالـ guild_id كـ doc_id
    (رومات، عداد الأكواد لكل تصنيف، لائحة المحظورين).
  • collection "resource_requests" → dict {request_id: {...}} كيفما باقي
    الكولكشنز المبنية بشكل key/value (نفس شكل db.load()/db.save()).
هاد الاختيار كيبقي التخزين ديال هاد النظام مبني على نفس الطبقة (db.py) لي
كيستعملها كل الكوجز الأخرى فالمشروع، عاد ماشي ملف SQLite منفصل كيتمسح مع كل
ديبلوي جديد فسيرفرات بلا Volume دائم (Heroku، Railway...).
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import db
import re
import uuid
import asyncio
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════════
#  Constants
# ══════════════════════════════════════════════════════════════════════════
SETTINGS_COLLECTION = "resource_settings"   # per-guild singleton doc (db.load_doc/save_doc)
REQUESTS_COLLECTION = "resource_requests"   # {request_id: {...}}         (db.load/save)

CATEGORY_NAME = "RESOURCES"

CATEGORIES = ["samp", "mods", "tools", "cheats", "bot-scripts", "other"]

CATEGORY_LABELS = {
    "samp": "📜 SA-MP Script",
    "mods": "🎨 Mods",
    "tools": "🛠️ Tools",
    "cheats": "💀 Cheats",
    "bot-scripts": "🤖 Bot Scripts",
    "other": "📂 Other",
}

CATEGORY_CHANNEL_NAMES = {
    "samp": "📜-samp",
    "mods": "🎨-mods",
    "tools": "🛠️-tools",
    "cheats": "💀-cheats",
    "bot-scripts": "🤖-bot-scripts",
    "other": "📂-other",
}
PENDING_CHANNEL_NAME = "📥-pending"
LOGS_CHANNEL_NAME = "📋-logs"

# Maps category -> settings doc field that holds its publish channel id
CHANNEL_KEY_BY_CATEGORY = {
    "samp": "ch_samp",
    "mods": "ch_mods",
    "tools": "ch_tools",
    "cheats": "ch_cheats",
    "bot-scripts": "ch_botscripts",
    "other": "ch_other",
}

CATEGORY_COLORS = {
    "samp": 0x57F287,
    "mods": 0xEB459E,
    "tools": 0xFEE75C,
    "cheats": 0xED4245,
    "bot-scripts": 0x5865F2,
    "other": 0x99AAB5,
}

CODE_PREFIX = {
    "samp": "SAMP",
    "mods": "MOD",
    "tools": "TOOL",
    "cheats": "CHEAT",
    "bot-scripts": "BOT",
    "other": "OTHER",
}

# All fields a settings document should always have, so `settings["x"]`
# direct-indexing works the same way it did against the old sqlite3.Row
# (every column existed there too, just NULL when unset).
SETTINGS_DEFAULT_FIELDS = {
    "category_id": None,
    "panel_channel_id": None,
    "review_role_id": None,
    "ch_samp": None, "ch_mods": None, "ch_tools": None,
    "ch_cheats": None, "ch_botscripts": None, "ch_other": None,
    "ch_pending": None, "ch_logs": None,
}

MAX_PENDING_PER_USER = 3
DM_TIMEOUT_SECONDS = 300
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
URL_RE = re.compile(r"https?://\S+")


# ══════════════════════════════════════════════════════════════════════════
#  MongoDB storage layer (via db.py) — same call shapes/behavior as the
#  original sqlite3 functions, just backed by Mongo instead of a local file.
# ══════════════════════════════════════════════════════════════════════════
def get_settings(guild_id: int) -> dict | None:
    doc = db.load_doc(SETTINGS_COLLECTION, str(guild_id))
    if not doc:
        return None
    merged = {**SETTINGS_DEFAULT_FIELDS, **doc}
    merged.setdefault("counters", {})
    merged.setdefault("banned_users", {})
    return merged


def save_settings(guild_id: int, **fields):
    doc = db.load_doc(SETTINGS_COLLECTION, str(guild_id))
    doc.update(fields)
    db.save_doc(SETTINGS_COLLECTION, doc, str(guild_id))


def create_request(**fields) -> str:
    fields["status"] = "pending"
    fields["submitted_at"] = datetime.now().isoformat()
    req_id = uuid.uuid4().hex[:10]
    requests_ = db.load(REQUESTS_COLLECTION)
    requests_[req_id] = fields
    db.save(REQUESTS_COLLECTION, requests_)
    return req_id


def get_request(req_id: str) -> dict | None:
    requests_ = db.load(REQUESTS_COLLECTION)
    return requests_.get(req_id)


def update_request(req_id: str, **fields):
    requests_ = db.load(REQUESTS_COLLECTION)
    if req_id in requests_:
        requests_[req_id].update(fields)
        db.save(REQUESTS_COLLECTION, requests_)


def count_pending(guild_id: int, author_id: int) -> int:
    requests_ = db.load(REQUESTS_COLLECTION)
    return sum(
        1 for r in requests_.values()
        if r.get("guild_id") == guild_id and r.get("author_id") == author_id and r.get("status") == "pending"
    )


def list_approved(guild_id: int, category: str | None = None) -> list[dict]:
    requests_ = db.load(REQUESTS_COLLECTION)
    rows = [
        r for r in requests_.values()
        if r.get("guild_id") == guild_id and r.get("status") == "approved"
        and (category is None or r.get("category") == category)
    ]
    rows.sort(key=lambda r: r.get("submitted_at", ""), reverse=True)
    return rows


def search_approved(guild_id: int, query: str) -> list[dict]:
    q = query.lower()
    requests_ = db.load(REQUESTS_COLLECTION)
    rows = [
        r for r in requests_.values()
        if r.get("guild_id") == guild_id and r.get("status") == "approved"
        and (
            q in (r.get("title") or "").lower()
            or q in (r.get("short_description") or "").lower()
            or q in (r.get("full_description") or "").lower()
        )
    ]
    rows.sort(key=lambda r: r.get("submitted_at", ""), reverse=True)
    return rows


def next_code(guild_id: int, category: str) -> str:
    doc = db.load_doc(SETTINGS_COLLECTION, str(guild_id))
    counters = doc.get("counters", {})
    n = counters.get(category, 1)
    counters[category] = n + 1
    doc["counters"] = counters
    db.save_doc(SETTINGS_COLLECTION, doc, str(guild_id))
    return f"{CODE_PREFIX[category]}-{n:03d}"


def is_banned(guild_id: int, user_id: int) -> bool:
    doc = db.load_doc(SETTINGS_COLLECTION, str(guild_id))
    return str(user_id) in doc.get("banned_users", {})


def ban_user(guild_id: int, user_id: int, banned_by_id: int):
    doc = db.load_doc(SETTINGS_COLLECTION, str(guild_id))
    banned = doc.get("banned_users", {})
    banned[str(user_id)] = {"banned_by": banned_by_id, "banned_at": datetime.now().isoformat()}
    doc["banned_users"] = banned
    db.save_doc(SETTINGS_COLLECTION, doc, str(guild_id))


def unban_user(guild_id: int, user_id: int) -> bool:
    doc = db.load_doc(SETTINGS_COLLECTION, str(guild_id))
    banned = doc.get("banned_users", {})
    existed = banned.pop(str(user_id), None) is not None
    doc["banned_users"] = banned
    db.save_doc(SETTINGS_COLLECTION, doc, str(guild_id))
    return existed


# ══════════════════════════════════════════════════════════════════════════
#  Channel / category bootstrap — /resource setup
# ══════════════════════════════════════════════════════════════════════════
async def _ensure_channels(guild: discord.Guild, review_role: discord.Role | None) -> tuple[int, dict]:
    """Creates the RESOURCES category + all 8 channels if missing (matched
    by name), returns (category_id, {key: channel_id})."""
    category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
    if category is None:
        category = await guild.create_category(CATEGORY_NAME)

    public_overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True),
    }
    staff_overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True),
    }
    if review_role:
        staff_overwrites[review_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    ids = {}
    for key, name in CATEGORY_CHANNEL_NAMES.items():
        ch = discord.utils.get(category.text_channels, name=name)
        if ch is None:
            ch = await guild.create_text_channel(name, category=category, overwrites=public_overwrites)
        ids[key] = ch.id

    pending_ch = discord.utils.get(category.text_channels, name=PENDING_CHANNEL_NAME)
    if pending_ch is None:
        pending_ch = await guild.create_text_channel(PENDING_CHANNEL_NAME, category=category, overwrites=staff_overwrites)
    ids["pending"] = pending_ch.id

    logs_ch = discord.utils.get(category.text_channels, name=LOGS_CHANNEL_NAME)
    if logs_ch is None:
        logs_ch = await guild.create_text_channel(LOGS_CHANNEL_NAME, category=category, overwrites=staff_overwrites)
    ids["logs"] = logs_ch.id

    return category.id, ids


# ══════════════════════════════════════════════════════════════════════════
#  Panel — Components V2 Container, same recipe as apply_system.ApplyButtonView
#  (kept the name main.py already imports/registers on startup)
# ══════════════════════════════════════════════════════════════════════════
class ResourceSubmitPanelView(discord.ui.LayoutView):
    """Persistent, guild-independent — one static panel, config is read live
    from MongoDB at click time, same pattern as TicketCreateView."""

    def __init__(self):
        super().__init__(timeout=None)
        heading = f"# 📦 {config.SERVER_NAME} — Resources"
        body = (
            "Got a SA-MP script, mod, tool, cheat-detection resource, Discord "
            "bot script, or anything else useful? Share it with the community.\n\n"
            "Every submission is reviewed by staff before it goes live."
        )
        btn = discord.ui.Button(
            label="Publish Resource",
            emoji="📦",
            style=discord.ButtonStyle.success,
            custom_id="res_panel_publish",
        )
        btn.callback = self.publish_click

        items = [
            discord.ui.TextDisplay(f"{heading}\n\n{body}"),
            discord.ui.Separator(),
            discord.ui.Section(discord.ui.TextDisplay("Ready to share something?"), accessory=btn),
        ]
        container = discord.ui.Container(*items, accent_color=0x3B82F6)
        self.add_item(container)

    async def publish_click(self, interaction: discord.Interaction):
        blocked = _submission_blocked(interaction)
        if blocked:
            await interaction.response.send_message(blocked, ephemeral=True)
            return
        await interaction.response.send_message(
            "Pick a category for your resource 👇", view=CategorySelectView(), ephemeral=True
        )


def _submission_blocked(interaction: discord.Interaction) -> str | None:
    """Returns an error string if the user shouldn't be allowed to submit
    right now, or None if they're clear to proceed."""
    settings = get_settings(interaction.guild_id)
    if not settings:
        return "❌ The resources system isn't set up yet — ask an admin to run `/resource setup`."
    if is_banned(interaction.guild_id, interaction.user.id):
        return "🚫 You've been banned from submitting resources."
    if count_pending(interaction.guild_id, interaction.user.id) >= MAX_PENDING_PER_USER:
        return f"❌ You already have {MAX_PENDING_PER_USER} requests awaiting review — wait for a decision before submitting another."
    return None


def _is_reviewer(interaction: discord.Interaction, settings: dict | None) -> bool:
    if interaction.user.guild_permissions.manage_guild:
        return True
    role_id = settings.get("review_role_id") if settings else None
    if role_id and any(r.id == int(role_id) for r in getattr(interaction.user, "roles", [])):
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════
#  Category dropdown → Modal
# ══════════════════════════════════════════════════════════════════════════
class CategorySelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=CATEGORY_LABELS[c], value=c) for c in CATEGORIES]
        super().__init__(placeholder="Choose a category...", options=options)

    async def callback(self, interaction: discord.Interaction):
        blocked = _submission_blocked(interaction)
        if blocked:
            await interaction.response.send_message(blocked, ephemeral=True)
            return
        await interaction.response.send_modal(ResourceModal(self.values[0]))


class CategorySelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(CategorySelect())


class ResourceModal(discord.ui.Modal, title="📦 New Resource"):
    resource_title = discord.ui.TextInput(label="Resource title", max_length=80)
    short_desc = discord.ui.TextInput(label="Short description", max_length=150)
    full_desc = discord.ui.TextInput(
        label="Full description",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        min_length=20,
    )

    def __init__(self, category: str):
        super().__init__()
        self.category = category

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _finish_submission(interaction, self.category, self.resource_title.value, self.short_desc.value, self.full_desc.value)


# ══════════════════════════════════════════════════════════════════════════
#  Optional image/file/link collection — Discord modals can't take file
#  uploads, so this is a normal message wait_for, done over DM (falling back
#  to the invoking channel if the user's DMs are closed).
# ══════════════════════════════════════════════════════════════════════════
async def _prompt_for_attachments(interaction: discord.Interaction, title: str):
    bot = interaction.client
    prompt = (
        f"**{title}** — reply here with an image and/or a file and/or a download "
        f"link (all optional). Type `skip` to continue without any.\n"
        f"⏱️ You have {DM_TIMEOUT_SECONDS // 60} minutes."
    )
    used_dm = True
    try:
        dm_channel = await interaction.user.create_dm()
        await dm_channel.send(prompt)
        await interaction.followup.send("📬 Check your DMs — reply there with an optional image/file/link.", ephemeral=True)
        target_channel_id = dm_channel.id
    except discord.Forbidden:
        used_dm = False
        await interaction.followup.send(
            "⚠️ I can't DM you — reply **right here in this channel** instead:\n" + prompt, ephemeral=True
        )
        target_channel_id = interaction.channel_id

    def check(m: discord.Message) -> bool:
        return m.author.id == interaction.user.id and m.channel.id == target_channel_id

    try:
        msg = await bot.wait_for("message", check=check, timeout=DM_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return None, None, None, used_dm

    image_file, other_file = None, None
    for att in msg.attachments:
        is_image = (att.content_type or "").startswith("image/") or att.filename.lower().endswith(IMAGE_EXTS)
        try:
            f = await att.to_file()
        except Exception:
            continue
        if is_image and image_file is None:
            image_file = f
        elif other_file is None:
            other_file = f

    link = None
    if msg.content and msg.content.strip().lower() not in ("skip", "تخطي", "لا", "-", "none"):
        found = URL_RE.search(msg.content)
        if found:
            link = found.group(0)

    return image_file, other_file, link, used_dm


async def _finish_submission(interaction: discord.Interaction, category: str, title: str, short_desc: str, full_desc: str):
    image_file, other_file, link, used_dm = await _prompt_for_attachments(interaction, title)

    settings = get_settings(interaction.guild_id)
    pending_channel = interaction.guild.get_channel(settings["ch_pending"]) if settings else None
    if not pending_channel:
        await interaction.followup.send("❌ The pending-review channel is missing — contact an admin.", ephemeral=True)
        return

    req_id = create_request(
        guild_id=interaction.guild_id,
        category=category,
        title=title,
        short_description=short_desc,
        full_description=full_desc,
        download_link=link,
        author_id=interaction.user.id,
        author_name=str(interaction.user),
    )

    embed = discord.Embed(
        title=f"📥 New Resource — {title}",
        description=full_desc[:2000],
        color=config.WARNING_COLOR,
        timestamp=datetime.now(),
    )
    embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
    embed.add_field(name="Category", value=CATEGORY_LABELS[category], inline=True)
    embed.add_field(name="Short description", value=short_desc, inline=False)
    embed.add_field(name="Download link", value=link or "—", inline=False)
    if other_file:
        embed.add_field(name="📎 Attached file", value=other_file.filename, inline=False)
    embed.set_footer(text=f"ID: {req_id} | {config.BOT_NAME}")

    files = [f for f in (image_file, other_file) if f]
    if image_file:
        embed.set_image(url=f"attachment://{image_file.filename}")

    msg = await pending_channel.send(embed=embed, view=ResourceReviewView(), files=files)
    update_request(req_id, pending_channel_id=pending_channel.id, pending_message_id=msg.id)

    confirm = discord.Embed(
        description=(
            "✅ Your resource was submitted for review! You'll get a DM once "
            "staff makes a decision."
            if used_dm else
            "✅ Your resource was submitted for review! Keep an eye on this "
            "channel — staff will reply with their decision."
        ),
        color=config.SUCCESS_COLOR,
    )
    await interaction.followup.send(embed=confirm, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════
#  Review view — persistent (Approve / Reject / Edit / Ban User), same
#  "read the request id from the embed footer" trick as the id-parsing
#  approach so it survives bot restarts without per-message custom_ids.
# ══════════════════════════════════════════════════════════════════════════
class ResourceReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def _get_request_id(self, message: discord.Message) -> str | None:
        try:
            footer = message.embeds[0].footer.text
            for part in footer.split("|"):
                part = part.strip()
                if part.startswith("ID:"):
                    return part.split(":", 1)[1].strip()
        except Exception:
            pass
        return None

    async def _guard(self, interaction: discord.Interaction) -> tuple[dict, dict] | None:
        """Common checks for every button: permission + request still pending.
        Returns (settings, request) on success, or None after replying with
        the relevant error."""
        settings = get_settings(interaction.guild_id)
        if not _is_reviewer(interaction, settings):
            await interaction.response.send_message("❌ You don't have permission to review resources.", ephemeral=True)
            return None

        req_id = self._get_request_id(interaction.message)
        req = get_request(req_id) if req_id else None
        if not req:
            await interaction.response.send_message("❌ This request no longer exists.", ephemeral=True)
            return None

        return settings, req, req_id  # type: ignore[return-value]

    @discord.ui.button(label="Approve", emoji="✅", style=discord.ButtonStyle.success, custom_id="res_review_approve")
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guard = await self._guard(interaction)
        if not guard:
            return
        settings, req, req_id = guard
        if req["status"] != "pending":
            await interaction.response.send_message(f"⚠️ Already handled (status: `{req['status']}`).", ephemeral=True)
            return
        await self._approve(interaction, settings, req, req_id)

    @discord.ui.button(label="Reject", emoji="❌", style=discord.ButtonStyle.danger, custom_id="res_review_reject")
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guard = await self._guard(interaction)
        if not guard:
            return
        settings, req, req_id = guard
        if req["status"] != "pending":
            await interaction.response.send_message(f"⚠️ Already handled (status: `{req['status']}`).", ephemeral=True)
            return
        await interaction.response.send_modal(RejectReasonModal(req_id))

    @discord.ui.button(label="Edit", emoji="✏️", style=discord.ButtonStyle.secondary, custom_id="res_review_edit")
    async def edit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guard = await self._guard(interaction)
        if not guard:
            return
        _, req, req_id = guard
        if req["status"] != "pending":
            await interaction.response.send_message(f"⚠️ Already handled (status: `{req['status']}`).", ephemeral=True)
            return
        await interaction.response.send_modal(EditRequestModal(req_id, req))

    @discord.ui.button(label="Ban User", emoji="🚫", style=discord.ButtonStyle.secondary, custom_id="res_review_ban")
    async def ban_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guard = await self._guard(interaction)
        if not guard:
            return
        settings, req, req_id = guard
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Only admins (`Manage Server`) can ban a submitter.", ephemeral=True)
            return

        ban_user(interaction.guild_id, req["author_id"], interaction.user.id)

        if req["status"] == "pending":
            update_request(req_id, status="rejected", reviewed_by_id=interaction.user.id,
                            reviewed_at=datetime.now().isoformat(), reject_reason="Banned by staff")

        await self._log(interaction.guild, f"🚫 {interaction.user.mention} banned <@{req['author_id']}> from "
                                            f"submitting resources and rejected **{req['title']}**.", config.ERROR_COLOR)

        author = interaction.guild.get_member(req["author_id"])
        if author:
            try:
                await author.send(embed=discord.Embed(
                    description=f"🚫 You've been banned from submitting resources in **{config.SERVER_NAME}**, "
                                f"and your pending resource **{req['title']}** was rejected.",
                    color=config.ERROR_COLOR,
                ))
            except discord.Forbidden:
                pass

        await self._finalize_message(interaction, status_line=f"🚫 **Banned & Rejected** by {interaction.user.mention}",
                                       color=config.ERROR_COLOR)

    async def _approve(self, interaction: discord.Interaction, settings: dict, req: dict, req_id: str):
        category = req["category"]
        code = next_code(interaction.guild_id, category)
        channel_key = CHANNEL_KEY_BY_CATEGORY[category]
        publish_channel_id = settings.get(channel_key)
        publish_channel = interaction.guild.get_channel(publish_channel_id) if publish_channel_id else None

        if not publish_channel:
            await interaction.response.send_message(
                "❌ The publish channel for this category is missing — contact an admin.", ephemeral=True
            )
            return

        pub_embed = discord.Embed(
            title=f"{CATEGORY_LABELS[category]} — {req['title']}",
            description=req["full_description"][:2000],
            color=CATEGORY_COLORS.get(category, config.EMBED_COLOR),
            timestamp=datetime.now(),
        )
        pub_embed.set_author(name=req["author_name"])
        pub_embed.add_field(name="Short description", value=req["short_description"], inline=False)
        if req.get("download_link"):
            pub_embed.add_field(name="Download", value=req["download_link"], inline=False)
        pub_embed.set_footer(text=f"{code} | Verified by Staff | {config.BOT_NAME}")

        pub_view = discord.ui.View()
        if req.get("download_link"):
            pub_view.add_item(discord.ui.Button(label="Download", emoji="⬇️", url=req["download_link"], style=discord.ButtonStyle.link))

        pub_msg = await publish_channel.send(embed=pub_embed, view=pub_view if pub_view.children else None)

        update_request(
            req_id,
            status="approved",
            resource_code=code,
            reviewed_by_id=interaction.user.id,
            reviewed_at=datetime.now().isoformat(),
            published_channel_id=publish_channel.id,
            published_message_id=pub_msg.id,
        )

        author = interaction.guild.get_member(req["author_id"])
        if author:
            try:
                await author.send(embed=discord.Embed(
                    description=f"✅ Your resource **{req['title']}** was approved and published as `{code}` "
                                f"in {publish_channel.mention}!",
                    color=config.SUCCESS_COLOR,
                ))
            except discord.Forbidden:
                pass

        await self._log(interaction.guild, f"✅ {interaction.user.mention} approved **{req['title']}** "
                                            f"({code}) → {publish_channel.mention}", config.SUCCESS_COLOR)

        await self._finalize_message(interaction, status_line=f"✅ **Approved** by {interaction.user.mention} — `{code}`",
                                      color=config.SUCCESS_COLOR)

    async def _finalize_message(self, interaction: discord.Interaction, status_line: str, color: int):
        embed = interaction.message.embeds[0]
        embed.color = color
        embed.add_field(name="Status", value=status_line, inline=False)
        for child in self.children:
            child.disabled = True
        if interaction.response.is_done():
            await interaction.message.edit(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    async def _log(self, guild: discord.Guild, text: str, color: int):
        settings = get_settings(guild.id)
        logs_channel = guild.get_channel(settings["ch_logs"]) if settings else None
        if logs_channel:
            try:
                await logs_channel.send(embed=discord.Embed(description=text, color=color, timestamp=datetime.now()))
            except (discord.Forbidden, discord.HTTPException):
                pass


class RejectReasonModal(discord.ui.Modal, title="❌ Reject Resource"):
    reason = discord.ui.TextInput(
        label="Reason (shown to the submitter)",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=False,
        placeholder="Optional — leave blank for no reason given",
    )

    def __init__(self, req_id: str):
        super().__init__()
        self.req_id = req_id

    async def on_submit(self, interaction: discord.Interaction):
        req = get_request(self.req_id)
        if not req or req["status"] != "pending":
            await interaction.response.send_message("⚠️ This request was already handled.", ephemeral=True)
            return

        update_request(self.req_id, status="rejected", reviewed_by_id=interaction.user.id,
                        reviewed_at=datetime.now().isoformat(), reject_reason=self.reason.value or None)

        author = interaction.guild.get_member(req["author_id"])
        if author:
            note = f"\nReason: {self.reason.value}" if self.reason.value else ""
            try:
                await author.send(embed=discord.Embed(
                    description=f"❌ Your resource **{req['title']}** was rejected by staff.{note}",
                    color=config.ERROR_COLOR,
                ))
            except discord.Forbidden:
                pass

        embed = interaction.message.embeds[0]
        embed.color = config.ERROR_COLOR
        status_line = f"❌ **Rejected** by {interaction.user.mention}"
        if self.reason.value:
            status_line += f"\nReason: {self.reason.value}"
        embed.add_field(name="Status", value=status_line, inline=False)

        new_view = ResourceReviewView()
        for child in new_view.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=new_view)

        settings = get_settings(interaction.guild_id)
        logs_channel = interaction.guild.get_channel(settings["ch_logs"]) if settings else None
        if logs_channel:
            try:
                await logs_channel.send(embed=discord.Embed(
                    description=f"❌ {interaction.user.mention} rejected **{req['title']}**"
                                 + (f"\nReason: {self.reason.value}" if self.reason.value else ""),
                    color=config.ERROR_COLOR, timestamp=datetime.now(),
                ))
            except (discord.Forbidden, discord.HTTPException):
                pass


class EditRequestModal(discord.ui.Modal, title="✏️ Edit Resource"):
    resource_title = discord.ui.TextInput(label="Resource title", max_length=80)
    short_desc = discord.ui.TextInput(label="Short description", max_length=150)
    full_desc = discord.ui.TextInput(label="Full description", style=discord.TextStyle.paragraph, max_length=2000, min_length=20)
    download_link = discord.ui.TextInput(label="Download link (optional)", max_length=300, required=False)

    def __init__(self, req_id: str, req: dict):
        super().__init__()
        self.req_id = req_id
        self.resource_title.default = req.get("title", "")
        self.short_desc.default = req.get("short_description", "")
        self.full_desc.default = req.get("full_description", "")
        self.download_link.default = req.get("download_link") or ""

    async def on_submit(self, interaction: discord.Interaction):
        req = get_request(self.req_id)
        if not req or req["status"] != "pending":
            await interaction.response.send_message("⚠️ This request was already handled.", ephemeral=True)
            return

        update_request(
            self.req_id,
            title=self.resource_title.value,
            short_description=self.short_desc.value,
            full_description=self.full_desc.value,
            download_link=self.download_link.value or None,
        )

        embed = interaction.message.embeds[0]
        embed.title = f"📥 New Resource — {self.resource_title.value}"
        embed.description = self.full_desc.value[:2000]
        for i, field in enumerate(embed.fields):
            if field.name == "Short description":
                embed.set_field_at(i, name="Short description", value=self.short_desc.value, inline=False)
            elif field.name == "Download link":
                embed.set_field_at(i, name="Download link", value=self.download_link.value or "—", inline=False)

        await interaction.response.edit_message(embed=embed, view=ResourceReviewView())
        await interaction.followup.send("✅ Edited — the request is still pending review.", ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════
#  Cog — slash commands
# ══════════════════════════════════════════════════════════════════════════
class Resources(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    resource_group = app_commands.Group(name="resource", description="📦 Resources system")

    @resource_group.command(name="setup", description="⚙️ (Admin) Set up the resources category, channels, and panel")
    @app_commands.describe(
        panel_channel="Channel where the single '📦 Publish Resource' panel button will be posted",
        review_role="Role that can approve/reject/edit resources, in addition to Manage Server (optional)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_cmd(self, interaction: discord.Interaction, panel_channel: discord.TextChannel, review_role: discord.Role = None):
        await interaction.response.defer(ephemeral=True, thinking=True)

        category_id, ids = await _ensure_channels(interaction.guild, review_role)

        fields = {"category_id": category_id, "panel_channel_id": panel_channel.id,
                  "review_role_id": review_role.id if review_role else None,
                  "ch_pending": ids["pending"], "ch_logs": ids["logs"]}
        for category, key in CHANNEL_KEY_BY_CATEGORY.items():
            fields[key] = ids[category]
        save_settings(interaction.guild_id, **fields)

        panel_embed_note = None
        try:
            await panel_channel.send(view=ResourceSubmitPanelView())
        except (discord.Forbidden, discord.HTTPException) as e:
            panel_embed_note = f"⚠️ Couldn't post the panel in {panel_channel.mention}: {e}"

        summary = discord.Embed(title="✅ Resources System Set Up", color=config.SUCCESS_COLOR)
        summary.add_field(name="Category", value=f"<#{ids['samp']}> and 5 more", inline=False)
        summary.add_field(name="Pending review", value=f"<#{ids['pending']}>", inline=True)
        summary.add_field(name="Logs", value=f"<#{ids['logs']}>", inline=True)
        summary.add_field(name="Panel", value=panel_channel.mention, inline=True)
        summary.add_field(name="Review role", value=review_role.mention if review_role else "Manage Server only", inline=True)
        if panel_embed_note:
            summary.add_field(name="Note", value=panel_embed_note, inline=False)
        await interaction.followup.send(embed=summary, ephemeral=True)

    @setup_cmd.error
    async def setup_cmd_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ You need `Manage Server` to use this command.", ephemeral=True)

    @resource_group.command(name="list", description="📋 Browse published resources")
    @app_commands.describe(category="Filter by category (optional)")
    @app_commands.choices(category=[app_commands.Choice(name=CATEGORY_LABELS[c], value=c) for c in CATEGORIES])
    async def list_cmd(self, interaction: discord.Interaction, category: app_commands.Choice[str] = None):
        rows = list_approved(interaction.guild_id, category.value if category else None)
        if not rows:
            await interaction.response.send_message("❌ No published resources match that filter yet.", ephemeral=True)
            return

        embed = discord.Embed(title=f"📋 Published Resources ({len(rows)})", color=config.EMBED_COLOR)
        for r in rows[:20]:
            desc = r["short_description"]
            embed.add_field(
                name=f"{r.get('resource_code', '—')} — {r['title']}",
                value=f"{desc}\nBy: {r['author_name']}",
                inline=False,
            )
        if len(rows) > 20:
            embed.set_footer(text=f"{len(rows) - 20} more — try /resource search")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @resource_group.command(name="search", description="🔍 Search published resources by keyword")
    @app_commands.describe(query="Keyword to search for")
    async def search_cmd(self, interaction: discord.Interaction, query: str):
        rows = search_approved(interaction.guild_id, query)
        if not rows:
            await interaction.response.send_message(f"❌ No results for `{query}`.", ephemeral=True)
            return

        embed = discord.Embed(title=f"🔍 Results for: {query}", color=config.EMBED_COLOR)
        for r in rows[:15]:
            embed.add_field(
                name=f"{r.get('resource_code', '—')} — {r['title']}",
                value=f"{r['short_description']}\nBy: {r['author_name']}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @resource_group.command(name="ban", description="🚫 (Staff) Ban a member from submitting resources")
    @app_commands.describe(user="Member to ban from submitting")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ban_cmd(self, interaction: discord.Interaction, user: discord.Member):
        ban_user(interaction.guild_id, user.id, interaction.user.id)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"🚫 {user.mention} can no longer submit resources.", color=config.SUCCESS_COLOR),
            ephemeral=True,
        )

    @resource_group.command(name="unban", description="✅ (Staff) Lift a resources submission ban")
    @app_commands.describe(user="Member to unban")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def unban_cmd(self, interaction: discord.Interaction, user: discord.Member):
        existed = unban_user(interaction.guild_id, user.id)
        if existed:
            msg, color = f"✅ {user.mention} can submit resources again.", config.SUCCESS_COLOR
        else:
            msg, color = f"⚠️ {user.mention} wasn't banned.", config.WARNING_COLOR
        await interaction.response.send_message(embed=discord.Embed(description=msg, color=color), ephemeral=True)

    @ban_cmd.error
    @unban_cmd.error
    async def ban_cmd_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ You need `Manage Server` to use this command.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Resources(bot))
