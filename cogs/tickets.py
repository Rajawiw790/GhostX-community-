"""
Ticket System — Ghostx Community
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Numbered ticket channels (ticket-0001) instead of usernames
- Multiple ticket types via a dropdown on the panel, each with its own
  category, support role and intake question
- Blacklist to block specific members from opening tickets
- Claim / Transfer / Close, with claim-locking (only the claimer or the
  ticket owner can close a claimed ticket)
- 5h no-staff-reply warning -> 30 more min -> auto-close
- Per-staff stats (claimed / closed)

Commands:
  /ticket setup                — panel channel + optional first ("General") type
  /ticket update                — change panel-level fields only
  /ticket remove                — disable the system for this server
  /ticket customize             — button labels/emoji + instructions text
  /ticket-type add/remove/list  — manage the dropdown's ticket types
  /ticket-blacklist add/remove/list — block/unblock members from opening tickets
  /ticket-add                   — add a member to the current ticket
  /ticket-close                 — close the current ticket
  /ticket-transfer              — hand a claimed ticket to another staff member
  /ticket-stats                 — per-staff or team leaderboard
"""

import io
import discord
from discord.ext import commands
from discord import app_commands
from discord.ext import tasks
import config
from datetime import datetime
import asyncio
import db

from cogs import panel_settings

TICKET_COLLECTION = "tickets"
BUTTON_COLLECTION = "ticket_buttons"
ACTIVITY_COLLECTION = "ticket_activity"
BLACKLIST_COLLECTION = "ticket_blacklist"
COUNTER_COLLECTION = "ticket_counter"
STATS_COLLECTION = "ticket_stats"

# No staff reply within this long → send one warning ping to the support role.
INACTIVITY_SECONDS = 5 * 3600
# Still nothing after the warning → auto-close the ticket.
CLOSE_GRACE_SECONDS = 30 * 60


# ─── Storage helpers ────────────────────────────────────────────────────────
def load_tickets() -> dict:
    return db.load(TICKET_COLLECTION)


def save_tickets(data: dict):
    db.save(TICKET_COLLECTION, data)


def load_activity() -> dict:
    return db.load(ACTIVITY_COLLECTION)


def save_activity(data: dict):
    db.save(ACTIVITY_COLLECTION, data)


def load_blacklist() -> dict:
    return db.load(BLACKLIST_COLLECTION)


def save_blacklist(data: dict):
    db.save(BLACKLIST_COLLECTION, data)


def load_stats() -> dict:
    return db.load(STATS_COLLECTION)


def save_stats(data: dict):
    db.save(STATS_COLLECTION, data)


def _next_ticket_number(guild_id: int) -> int:
    counters = db.load(COUNTER_COLLECTION)
    gid = str(guild_id)
    n = counters.get(gid, 0) + 1
    counters[gid] = n
    db.save(COUNTER_COLLECTION, counters)
    return n


BUTTON_DEFAULTS = {
    "dropdown_placeholder": "Select a ticket type...",
    "claim_label": "Claim",
    "claim_emoji": None,
    "close_label": "Close",
    "close_emoji": None,
}


def load_btn(guild_id: int) -> dict:
    data = db.load_doc(BUTTON_COLLECTION, doc_id=str(guild_id))
    return {**BUTTON_DEFAULTS, **data}


def save_btn(guild_id: int, data: dict):
    db.save_doc(BUTTON_COLLECTION, data, doc_id=str(guild_id))


def _record_stat(guild_id: int, user_id: int, field: str):
    stats = load_stats()
    gid = str(guild_id)
    s = stats.setdefault(gid, {}).setdefault(str(user_id), {"claimed": 0, "closed": 0})
    s[field] = s.get(field, 0) + 1
    save_stats(stats)


# ─── Permission helpers ─────────────────────────────────────────────────────
def _is_support_staff(member: discord.Member, cfg: dict) -> bool:
    """True for anyone who should be able to act as staff anywhere in the
    ticket system: Manage Channels permission, or any configured support
    role across the guild's ticket types."""
    if member.guild_permissions.manage_channels:
        return True
    role_ids = {t.get("support_role_id") for t in cfg.get("types", {}).values() if t.get("support_role_id")}
    if role_ids:
        member_role_ids = {r.id for r in member.roles}
        if role_ids.intersection(member_role_ids):
            return True
    return False


def _get_claimed_by(channel_id: int) -> int | None:
    activity = load_activity()
    rec = activity.get(str(channel_id))
    return rec.get("claimed_by") if rec else None


def _can_close_ticket(member: discord.Member, channel: discord.TextChannel, cfg: dict) -> bool:
    """- Always: the ticket owner.
    - Unclaimed ticket: any support staff.
    - Claimed ticket: only the staff member who claimed it."""
    is_owner = channel.topic == str(member.id)
    if is_owner:
        return True

    claimed_by = _get_claimed_by(channel.id)
    if claimed_by:
        return member.id == claimed_by

    return _is_support_staff(member, cfg)


# ─── Problem Modal ──────────────────────────────────────────────────────────
class ProblemModal(discord.ui.Modal, title="Open a Ticket"):
    def __init__(self, type_key: str, question: str):
        super().__init__()
        self.type_key = type_key
        self.problem = discord.ui.TextInput(
            label=question[:45],
            style=discord.TextStyle.paragraph,
            placeholder="Describe your issue clearly so the team can help you quickly...",
            min_length=5,
            max_length=1000,
        )
        self.add_item(self.problem)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await _create_ticket(interaction, self.type_key, self.problem.value)


# ─── Create ticket channel ──────────────────────────────────────────────────
async def _create_ticket(interaction: discord.Interaction, type_key: str, problem_text: str):
    ts = load_tickets()
    cfg = ts.get(str(interaction.guild_id))
    if not cfg:
        await interaction.followup.send("Ticket system is not configured. Use `/ticket setup`.", ephemeral=True)
        return

    t = cfg.get("types", {}).get(type_key)
    if not t:
        await interaction.followup.send("This ticket type is no longer available.", ephemeral=True)
        return

    # One open ticket per member at a time, across ALL types/categories.
    activity = load_activity()
    for ch_id, rec in activity.items():
        if rec.get("guild_id") == interaction.guild_id and rec.get("owner_id") == interaction.user.id:
            existing = interaction.guild.get_channel(int(ch_id))
            if existing:
                await interaction.followup.send(f"You already have an open ticket: {existing.mention}", ephemeral=True)
                return

    category = interaction.guild.get_channel(t.get("category_id"))

    overwrites = {}
    if category:
        overwrites.update(category.overwrites)

    overwrites[interaction.guild.default_role] = discord.PermissionOverwrite(read_messages=False)
    overwrites[interaction.user] = discord.PermissionOverwrite(
        read_messages=True, send_messages=True, attach_files=True
    )
    overwrites[interaction.guild.me] = discord.PermissionOverwrite(
        read_messages=True, send_messages=True, manage_channels=True, manage_messages=True
    )

    support_role = None
    support_role_id = t.get("support_role_id")
    if support_role_id:
        support_role = interaction.guild.get_role(support_role_id)
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    number = _next_ticket_number(interaction.guild_id)
    ch_name = f"ticket-{number:04d}"

    try:
        ticket_channel = await interaction.guild.create_text_channel(
            name=ch_name,
            topic=str(interaction.user.id),
            category=category,
            overwrites=overwrites,
        )
    except Exception as e:
        await interaction.followup.send(f"Failed to create ticket channel: {e}", ephemeral=True)
        return

    note_text = cfg.get("panel_message") or panel_settings.render(panel_settings.get("ticket_instructions_text")) or (
        "Please write what you need — our team will be with you shortly."
    )
    reason_label = panel_settings.get("ticket_reason_label") or "Ticket Reason"

    opened_line = f"{interaction.user.mention} • <t:{int(datetime.now().timestamp())}:R>"
    if support_role:
        opened_line += f" • {support_role.mention}"

    embed = discord.Embed(
        title=f"Ticket #{number:04d} — {t['label']}",
        description=f"**{reason_label}**\n>>> {problem_text[:350]}",
        color=config.EMBED_COLOR,
        timestamp=datetime.now(),
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)

    banner_url = cfg.get("banner_url") or ""
    if banner_url:
        embed.set_image(url=banner_url)

    embed.add_field(name="Opened by", value=opened_line, inline=False)
    embed.add_field(name="Note", value=note_text[:200], inline=False)
    embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

    ping_parts = [interaction.user.mention]
    if support_role:
        ping_parts.append(support_role.mention)

    await ticket_channel.send(
        content=" ".join(ping_parts),
        embed=embed,
        view=TicketControlView(interaction.guild_id),
        allowed_mentions=discord.AllowedMentions(users=True, roles=True),
    )
    await interaction.followup.send(f"Your ticket has been created: {ticket_channel.mention}", ephemeral=True)

    activity = load_activity()
    activity[str(ticket_channel.id)] = {
        "guild_id": interaction.guild_id,
        "owner_id": interaction.user.id,
        "type_key": type_key,
        "ticket_number": number,
        "opened_at": datetime.now().timestamp(),
        "last_reply_at": None,
        "warned": False,
        "warned_at": None,
        "claimed_by": None,
    }
    save_activity(activity)


# ─── Ticket type dropdown (on /ticket setup panel) ─────────────────────────
class TicketTypeSelect(discord.ui.Select):
    def __init__(self, options, disabled: bool = False, placeholder: str = "Select a ticket type..."):
        super().__init__(
            placeholder=placeholder,
            options=options,
            custom_id="ticket_type_select",
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        type_key = self.values[0]

        bl = load_blacklist()
        if interaction.user.id in bl.get(str(interaction.guild_id), []):
            await interaction.response.send_message("You're not allowed to open tickets.", ephemeral=True)
            return

        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        t = cfg.get("types", {}).get(type_key)
        if not t:
            await interaction.response.send_message("This ticket type is no longer available.", ephemeral=True)
            return

        await interaction.response.send_modal(
            ProblemModal(type_key, t.get("question") or "What do you need help with?")
        )


class TicketCreateView(discord.ui.View):
    def __init__(self, guild_id: int = 0, types: dict = None):
        super().__init__(timeout=None)
        types = types or {}
        btn = load_btn(guild_id)

        if types:
            options = [
                discord.SelectOption(
                    label=t["label"][:100],
                    value=key,
                    description=(t.get("description") or None),
                    emoji=t.get("emoji") or None,
                )
                for key, t in types.items()
            ][:25]
            self.add_item(TicketTypeSelect(options, placeholder=btn.get("dropdown_placeholder", "Select a ticket type...")))
        else:
            self.add_item(
                TicketTypeSelect(
                    [discord.SelectOption(label="No ticket types configured", value="_none")],
                    disabled=True,
                    placeholder="No ticket types configured",
                )
            )


# ─── Ticket Control Buttons (inside the ticket channel) ────────────────────
class TicketControlView(discord.ui.View):
    def __init__(self, guild_id: int = 0):
        super().__init__(timeout=None)
        btn = load_btn(guild_id)
        self.claim.label = btn["claim_label"]
        self.claim.emoji = btn["claim_emoji"]
        self.close.label = btn["close_label"]
        self.close.emoji = btn["close_emoji"]
        self.support_panel.label = panel_settings.get("ticket_support_panel_label") or "Support Panel"
        self.support_panel.emoji = panel_settings.get("ticket_support_panel_emoji") or None

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, custom_id="ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        if not _is_support_staff(interaction.user, cfg):
            await interaction.response.send_message("Only support staff can claim tickets.", ephemeral=True)
            return

        activity = load_activity()
        ch_key = str(interaction.channel_id)
        rec = activity.get(ch_key)
        if rec and rec.get("claimed_by") and rec["claimed_by"] != interaction.user.id:
            claimer = interaction.guild.get_member(rec["claimed_by"])
            await interaction.response.send_message(
                f"Already claimed by {claimer.mention if claimer else 'another staff member'}.", ephemeral=True
            )
            return

        if not rec:
            rec = {
                "guild_id": interaction.guild_id,
                "owner_id": int(interaction.channel.topic) if interaction.channel.topic and interaction.channel.topic.isdigit() else None,
                "type_key": None,
                "ticket_number": None,
                "opened_at": datetime.now().timestamp(),
                "last_reply_at": None,
                "warned": False,
                "warned_at": None,
            }
        rec["claimed_by"] = interaction.user.id
        activity[ch_key] = rec
        save_activity(activity)
        _record_stat(interaction.guild_id, interaction.user.id, "claimed")

        embed = discord.Embed(
            description=(
                f"This ticket has been claimed by {interaction.user.mention}.\n"
                f"Only {interaction.user.mention} or the ticket owner can close it from now on."
            ),
            color=config.SUCCESS_COLOR,
            timestamp=datetime.now(),
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

        button.disabled = True
        button.label = f"Claimed by {interaction.user.display_name}"
        await interaction.message.edit(view=self)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="ticket_close_btn")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        if not _can_close_ticket(interaction.user, interaction.channel, cfg):
            claimed_by = _get_claimed_by(interaction.channel_id)
            if claimed_by:
                claimer = interaction.guild.get_member(claimed_by)
                await interaction.response.send_message(
                    f"This ticket is claimed by {claimer.mention if claimer else 'another staff member'} — "
                    f"only they or the ticket owner can close it.", ephemeral=True
                )
            else:
                await interaction.response.send_message("Only support staff or the ticket owner can close this.", ephemeral=True)
            return

        await interaction.response.send_message(
            embed=discord.Embed(
                description="This ticket will be closed and logged in 5 seconds...",
                color=config.WARNING_COLOR,
            )
        )
        await asyncio.sleep(5)
        await _save_transcript_and_delete(interaction.channel, interaction.guild, closed_by=interaction.user.id)

    @discord.ui.button(label="Support Panel", style=discord.ButtonStyle.secondary, custom_id="ticket_support_panel")
    async def support_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        activity = load_activity()
        rec = activity.get(str(interaction.channel_id), {})
        t = cfg.get("types", {}).get(rec.get("type_key")) if rec.get("type_key") else None
        support_role = interaction.guild.get_role(t.get("support_role_id") or 0) if t else None
        claimed_by = _get_claimed_by(interaction.channel_id)
        claimer = interaction.guild.get_member(claimed_by) if claimed_by else None

        lines = [
            f"Support role: {support_role.mention if support_role else 'none configured'}",
            f"Claimed by: {claimer.mention if claimer else 'not claimed yet'}",
            "",
            "Available commands in this ticket:",
            "`/ticket-add` — add another member",
            "`/ticket-transfer` — hand this ticket to another staff member",
            "`/ticket-close` — close this ticket",
        ]
        embed = discord.Embed(description="\n".join(lines), color=config.EMBED_COLOR)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ─── Transcript save and channel delete ─────────────────────────────────────
async def _save_transcript_and_delete(channel: discord.TextChannel, guild: discord.Guild, closed_by: int = None):
    activity = load_activity()
    rec = activity.pop(str(channel.id), None)
    save_activity(activity)

    if closed_by:
        _record_stat(guild.id, closed_by, "closed")

    ts = load_tickets()
    cfg = ts.get(str(guild.id), {})
    log_ch_id = cfg.get("log_channel_id")

    if log_ch_id:
        log_channel = guild.get_channel(log_ch_id)
        if log_channel:
            lines = []
            async for msg in channel.history(limit=500, oldest_first=True):
                ts_time = msg.created_at.strftime("%Y-%m-%d %H:%M")
                content = msg.content or "[embed/attachment]"
                lines.append(f"[{ts_time}] {msg.author.display_name}: {content}")

            transcript_text = "\n".join(lines) if lines else "No messages."
            file_obj = discord.File(io.BytesIO(transcript_text.encode("utf-8")), filename=f"transcript-{channel.name}.txt")

            owner_id = rec.get("owner_id") if rec else channel.topic
            owner_mention = f"<@{owner_id}>" if owner_id else "Unknown"

            type_label = None
            if rec and rec.get("type_key"):
                t = cfg.get("types", {}).get(rec["type_key"])
                type_label = t["label"] if t else rec["type_key"]

            desc = f"**Channel:** #{channel.name}\n**Owner:** {owner_mention}\n**Closed at:** <t:{int(datetime.now().timestamp())}:F>"
            if type_label:
                desc += f"\n**Type:** {type_label}"
            if closed_by:
                desc += f"\n**Closed by:** <@{closed_by}>"

            embed = discord.Embed(title="Ticket Transcript", description=desc, color=config.EMBED_COLOR, timestamp=datetime.now())
            embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
            await log_channel.send(embed=embed, file=file_obj)

    try:
        await channel.delete()
    except Exception:
        pass


# ─── Tickets Cog ─────────────────────────────────────────────────────────────
class Tickets(commands.Cog):
    ticket_group = app_commands.Group(
        name="ticket",
        description="Manage the ticket system",
        default_permissions=discord.Permissions(administrator=True),
    )
    ticket_type_group = app_commands.Group(
        name="ticket-type",
        description="Manage the ticket types shown in the panel dropdown",
        default_permissions=discord.Permissions(administrator=True),
    )
    ticket_blacklist_group = app_commands.Group(
        name="ticket-blacklist",
        description="Block or unblock members from opening tickets",
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(self, bot):
        self.bot = bot
        self.check_inactive_tickets.start()

    async def cog_unload(self):
        self.check_inactive_tickets.cancel()

    # ── Any support-staff message inside a tracked ticket resets its clock ──
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        activity = load_activity()
        ch_key = str(message.channel.id)
        rec = activity.get(ch_key)
        if not rec:
            return
        ts = load_tickets()
        cfg = ts.get(str(message.guild.id), {})
        if not isinstance(message.author, discord.Member) or not _is_support_staff(message.author, cfg):
            return
        rec["last_reply_at"] = datetime.now().timestamp()
        rec["warned"] = False
        rec["warned_at"] = None
        activity[ch_key] = rec
        save_activity(activity)

    # ── Background task — 5h no-reply -> warning, 30 more min -> auto-close ──
    @tasks.loop(minutes=10)
    async def check_inactive_tickets(self):
        activity = load_activity()
        if not activity:
            return
        now = datetime.now().timestamp()
        changed = False

        for ch_key, rec in list(activity.items()):
            try:
                guild = self.bot.get_guild(rec.get("guild_id"))
                channel = guild.get_channel(int(ch_key)) if guild else None
                if not guild or not channel:
                    activity.pop(ch_key, None)
                    changed = True
                    continue

                last_activity = rec.get("last_reply_at") or rec.get("opened_at", now)

                if not rec.get("warned"):
                    if now - last_activity < INACTIVITY_SECONDS:
                        continue
                    ts = load_tickets()
                    cfg = ts.get(str(rec.get("guild_id")), {})
                    t = cfg.get("types", {}).get(rec.get("type_key")) if rec.get("type_key") else None
                    support_role = guild.get_role(t.get("support_role_id") or 0) if t else None
                    embed = discord.Embed(
                        title="Still waiting on a reply",
                        description=(
                            f"No one from support has answered this ticket in over "
                            f"**{INACTIVITY_SECONDS // 3600} hours**. It will close "
                            f"automatically in **{CLOSE_GRACE_SECONDS // 60} minutes** "
                            f"if it stays quiet."
                        ),
                        color=config.WARNING_COLOR,
                        timestamp=datetime.now(),
                    )
                    embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
                    try:
                        await channel.send(
                            content=support_role.mention if support_role else None,
                            embed=embed,
                            allowed_mentions=discord.AllowedMentions(roles=True),
                        )
                    except Exception:
                        pass
                    rec["warned"] = True
                    rec["warned_at"] = now
                    activity[ch_key] = rec
                    changed = True
                else:
                    if now - rec.get("warned_at", now) >= CLOSE_GRACE_SECONDS:
                        await _save_transcript_and_delete(channel, guild)
                        activity.pop(ch_key, None)
                        changed = True
            except Exception as e:
                print(f"[Tickets] inactivity check failed for channel {ch_key}: {e}")

        if changed:
            save_activity(activity)

    @check_inactive_tickets.before_loop
    async def before_check_inactive_tickets(self):
        await self.bot.wait_until_ready()

    # ── panel posting/refresh ─────────────────────────────────────────────
    async def _post_or_refresh_panel(self, guild: discord.Guild, cfg: dict):
        channel = guild.get_channel(cfg.get("panel_channel_id") or 0)
        if not channel:
            return

        embed = discord.Embed(
            title=cfg.get("panel_title", "Support Tickets"),
            description=cfg.get("panel_message", "Select a category below to open a ticket."),
            color=config.EMBED_COLOR,
        )
        if cfg.get("banner_url"):
            embed.set_image(url=cfg["banner_url"])
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

        view = TicketCreateView(guild.id, cfg.get("types", {}))

        msg = None
        msg_id = cfg.get("panel_message_id")
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
            except Exception:
                msg = None

        if msg:
            await msg.edit(embed=embed, view=view)
        else:
            msg = await channel.send(embed=embed, view=view)
            ts = load_tickets()
            gcfg = ts.setdefault(str(guild.id), cfg)
            gcfg["panel_message_id"] = msg.id
            save_tickets(ts)

    # ─── /ticket setup ────────────────────────────────────────────────────
    @ticket_group.command(name="setup", description="Set up the ticket system")
    @app_commands.describe(
        panel_channel="Channel where the ticket panel will be posted",
        category="Category for the default 'General' ticket type (optional — add more with /ticket-type add)",
        support_role="Support role for the default 'General' ticket type (optional)",
        log_channel="Channel where closed ticket transcripts are sent (optional)",
        panel_title="Title of the panel embed (optional)",
        panel_message="Panel embed description, also shown inside opened tickets (optional)",
        banner_url="Banner image URL for the ticket embed (optional)",
    )
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
        panel_channel: discord.TextChannel,
        category: discord.CategoryChannel = None,
        support_role: discord.Role = None,
        log_channel: discord.TextChannel = None,
        panel_title: str = None,
        panel_message: str = None,
        banner_url: str = None,
    ):
        ts = load_tickets()
        gid = str(interaction.guild_id)
        cfg = ts.get(gid, {"types": {}})

        cfg["panel_channel_id"] = panel_channel.id
        if log_channel:
            cfg["log_channel_id"] = log_channel.id
        cfg["panel_title"] = panel_title or cfg.get("panel_title", "Support Tickets")
        cfg["panel_message"] = panel_message or cfg.get("panel_message", "Select a category below to open a ticket.")
        if banner_url is not None:
            cfg["banner_url"] = banner_url
        cfg.setdefault("types", {})

        if category or support_role:
            existing = cfg["types"].get("general", {})
            cfg["types"]["general"] = {
                "label": "General",
                "emoji": None,
                "description": existing.get("description", "General support"),
                "category_id": category.id if category else existing.get("category_id"),
                "support_role_id": support_role.id if support_role else existing.get("support_role_id"),
                "question": existing.get("question", "What do you need help with?"),
            }

        ts[gid] = cfg
        save_tickets(ts)

        if not cfg["types"]:
            await interaction.response.send_message(
                "Panel channel saved, but no ticket types are configured yet — "
                "add one with `/ticket-type add` before members can open tickets.",
                ephemeral=True,
            )
            return

        await self._post_or_refresh_panel(interaction.guild, cfg)
        await interaction.response.send_message(
            embed=self._summary_embed("Ticket System Set Up", cfg), ephemeral=True
        )

    # ─── /ticket update ──────────────────────────────────────────────────
    @ticket_group.command(name="update", description="Update panel-level ticket settings (types are managed with /ticket-type)")
    @app_commands.describe(
        panel_channel="New panel channel (optional)",
        log_channel="New transcript log channel (optional)",
        panel_title="New panel embed title (optional)",
        panel_message="New panel description, also shown inside tickets (optional)",
        banner_url="New banner image URL (optional)",
    )
    async def ticket_update(
        self,
        interaction: discord.Interaction,
        panel_channel: discord.TextChannel = None,
        log_channel: discord.TextChannel = None,
        panel_title: str = None,
        panel_message: str = None,
        banner_url: str = None,
    ):
        ts = load_tickets()
        gid = str(interaction.guild_id)
        cfg = ts.get(gid)
        if not cfg:
            await interaction.response.send_message("Ticket system not set up yet. Use `/ticket setup` first.", ephemeral=True)
            return

        if panel_channel:
            cfg["panel_channel_id"] = panel_channel.id
            cfg["panel_message_id"] = None  # new channel -> post fresh instead of editing the old one
        if log_channel:   cfg["log_channel_id"] = log_channel.id
        if panel_title:   cfg["panel_title"] = panel_title
        if panel_message: cfg["panel_message"] = panel_message
        if banner_url is not None: cfg["banner_url"] = banner_url

        ts[gid] = cfg
        save_tickets(ts)

        if cfg.get("types"):
            await self._post_or_refresh_panel(interaction.guild, cfg)

        await interaction.response.send_message(
            embed=self._summary_embed("Ticket Settings Updated", cfg), ephemeral=True
        )

    # ─── /ticket remove ──────────────────────────────────────────────────
    @ticket_group.command(name="remove", description="Remove the ticket system setup")
    async def ticket_remove(self, interaction: discord.Interaction):
        ts = load_tickets()
        ts.pop(str(interaction.guild_id), None)
        save_tickets(ts)
        embed = discord.Embed(
            description="The ticket system has been disabled for this server.",
            color=config.ERROR_COLOR,
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─── /ticket customize ───────────────────────────────────────────────
    @ticket_group.command(name="customize", description="Customize button labels/emoji, dropdown text, and the instructions text")
    @app_commands.describe(
        dropdown_placeholder="Text shown on the panel's dropdown before a selection (optional)",
        claim_label="Claim button label (optional)", claim_emoji="Claim button emoji (optional)",
        close_label="Close button label (optional)", close_emoji="Close button emoji (optional)",
        instructions_text="Important-instructions text shown in every ticket (optional)",
    )
    async def ticket_customize(
        self,
        interaction: discord.Interaction,
        dropdown_placeholder: str = None,
        claim_label: str = None, claim_emoji: str = None,
        close_label: str = None, close_emoji: str = None,
        instructions_text: str = None,
    ):
        if not any([dropdown_placeholder, claim_label, claim_emoji, close_label, close_emoji, instructions_text]):
            await interaction.response.send_message("Provide at least one field to change.", ephemeral=True)
            return

        btn = load_btn(interaction.guild_id)
        if dropdown_placeholder: btn["dropdown_placeholder"] = dropdown_placeholder
        if claim_label:  btn["claim_label"] = claim_label
        if claim_emoji:  btn["claim_emoji"] = claim_emoji
        if close_label:  btn["close_label"] = close_label
        if close_emoji:  btn["close_emoji"] = close_emoji
        save_btn(interaction.guild_id, btn)

        if instructions_text:
            panel_settings.set_values(ticket_instructions_text=instructions_text)

        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id))
        if cfg and cfg.get("types"):
            await self._post_or_refresh_panel(interaction.guild, cfg)

        await interaction.response.send_message(
            embed=discord.Embed(description="Ticket panel customized.", color=config.SUCCESS_COLOR),
            ephemeral=True,
        )

    # ─── /ticket-type add/remove/list ────────────────────────────────────
    @ticket_type_group.command(name="add", description="Add (or update) a ticket type shown in the panel dropdown")
    @app_commands.describe(
        label="Name shown in the dropdown (e.g. 'Billing')",
        category="Category new tickets of this type are created in",
        support_role="Role that can see and claim this type of ticket",
        emoji="Emoji shown next to this option (optional)",
        question="Question shown in the intake form (optional)",
        description="Short text shown under the option in the dropdown (optional)",
    )
    async def type_add(
        self,
        interaction: discord.Interaction,
        label: str,
        category: discord.CategoryChannel,
        support_role: discord.Role,
        emoji: str = None,
        question: str = None,
        description: str = None,
    ):
        ts = load_tickets()
        gid = str(interaction.guild_id)
        cfg = ts.get(gid)
        if not cfg:
            await interaction.response.send_message("Run `/ticket setup` first.", ephemeral=True)
            return

        key = label.lower().strip().replace(" ", "_")[:80]
        cfg.setdefault("types", {})[key] = {
            "label": label[:100],
            "emoji": emoji,
            "description": (description or "")[:100],
            "category_id": category.id,
            "support_role_id": support_role.id,
            "question": question or "What do you need help with?",
        }
        ts[gid] = cfg
        save_tickets(ts)

        await self._post_or_refresh_panel(interaction.guild, cfg)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"Ticket type **{label}** saved.", color=config.SUCCESS_COLOR),
            ephemeral=True,
        )

    @ticket_type_group.command(name="remove", description="Remove a ticket type from the panel dropdown")
    @app_commands.describe(label="The exact label of the ticket type to remove")
    async def type_remove(self, interaction: discord.Interaction, label: str):
        ts = load_tickets()
        gid = str(interaction.guild_id)
        cfg = ts.get(gid)
        key = label.lower().strip().replace(" ", "_")[:80]
        if not cfg or key not in cfg.get("types", {}):
            await interaction.response.send_message("Ticket type not found.", ephemeral=True)
            return

        cfg["types"].pop(key)
        ts[gid] = cfg
        save_tickets(ts)

        await self._post_or_refresh_panel(interaction.guild, cfg)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"Ticket type **{label}** removed.", color=config.SUCCESS_COLOR),
            ephemeral=True,
        )

    @ticket_type_group.command(name="list", description="List the ticket types configured for this server")
    async def type_list(self, interaction: discord.Interaction):
        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        types = cfg.get("types", {})
        if not types:
            await interaction.response.send_message("No ticket types configured.", ephemeral=True)
            return

        lines = []
        for t in types.values():
            cat = interaction.guild.get_channel(t.get("category_id"))
            role = interaction.guild.get_role(t.get("support_role_id"))
            lines.append(f"**{t['label']}** — category: {cat.mention if cat else 'none'}, role: {role.mention if role else 'none'}")

        embed = discord.Embed(title="Ticket Types", description="\n".join(lines), color=config.EMBED_COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─── /ticket-blacklist add/remove/list ───────────────────────────────
    @ticket_blacklist_group.command(name="add", description="Block a member from opening tickets")
    @app_commands.describe(member="The member to block")
    async def blacklist_add(self, interaction: discord.Interaction, member: discord.Member):
        bl = load_blacklist()
        gid = str(interaction.guild_id)
        lst = bl.setdefault(gid, [])
        if member.id not in lst:
            lst.append(member.id)
        save_blacklist(bl)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"{member.mention} can no longer open tickets.", color=config.SUCCESS_COLOR),
            ephemeral=True,
        )

    @ticket_blacklist_group.command(name="remove", description="Unblock a member from opening tickets")
    @app_commands.describe(member="The member to unblock")
    async def blacklist_remove(self, interaction: discord.Interaction, member: discord.Member):
        bl = load_blacklist()
        gid = str(interaction.guild_id)
        lst = bl.get(gid, [])
        if member.id in lst:
            lst.remove(member.id)
        save_blacklist(bl)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"{member.mention} can open tickets again.", color=config.SUCCESS_COLOR),
            ephemeral=True,
        )

    @ticket_blacklist_group.command(name="list", description="Show blocked members")
    async def blacklist_list(self, interaction: discord.Interaction):
        bl = load_blacklist()
        ids = bl.get(str(interaction.guild_id), [])
        if not ids:
            await interaction.response.send_message("The blacklist is empty.", ephemeral=True)
            return
        embed = discord.Embed(description="\n".join(f"<@{uid}>" for uid in ids), color=config.EMBED_COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Add member to ticket ──────────────────────────────────────────────
    @app_commands.command(name="ticket-add", description="Add a member to the current ticket")
    @app_commands.describe(member="The member to add")
    async def ticket_add(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.channel.name.startswith("ticket-"):
            await interaction.response.send_message("This command only works inside a ticket channel.", ephemeral=True)
            return
        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        if not _is_support_staff(interaction.user, cfg):
            await interaction.response.send_message("Support staff only.", ephemeral=True)
            return
        await interaction.channel.set_permissions(member, read_messages=True, send_messages=True)
        embed = discord.Embed(description=f"{member.mention} has been added to this ticket.", color=config.SUCCESS_COLOR)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

    # ── Transfer a claimed ticket to another staff member ────────────────
    @app_commands.command(name="ticket-transfer", description="Hand this claimed ticket to another staff member")
    @app_commands.describe(member="The staff member to transfer this ticket to")
    async def ticket_transfer(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.channel.name.startswith("ticket-"):
            await interaction.response.send_message("This command only works inside a ticket channel.", ephemeral=True)
            return

        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        if not _is_support_staff(member, cfg):
            await interaction.response.send_message(f"{member.mention} is not support staff.", ephemeral=True)
            return

        activity = load_activity()
        ch_key = str(interaction.channel_id)
        rec = activity.get(ch_key)
        claimed_by = rec.get("claimed_by") if rec else None

        if not claimed_by:
            await interaction.response.send_message("This ticket hasn't been claimed yet — use Claim first.", ephemeral=True)
            return
        if interaction.user.id != claimed_by and not interaction.user.guild_permissions.administrator:
            claimer = interaction.guild.get_member(claimed_by)
            await interaction.response.send_message(
                f"Only {claimer.mention if claimer else 'the current claimer'} can transfer this ticket.", ephemeral=True
            )
            return

        rec["claimed_by"] = member.id
        activity[ch_key] = rec
        save_activity(activity)

        await interaction.response.send_message(
            embed=discord.Embed(description=f"This ticket has been transferred to {member.mention}.", color=config.EMBED_COLOR)
        )

    # ── Close ticket by command ───────────────────────────────────────────
    @app_commands.command(name="ticket-close", description="Close the current ticket")
    async def ticket_close(self, interaction: discord.Interaction):
        if not interaction.channel.name.startswith("ticket-"):
            await interaction.response.send_message("This command only works inside a ticket channel.", ephemeral=True)
            return
        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        if not _can_close_ticket(interaction.user, interaction.channel, cfg):
            claimed_by = _get_claimed_by(interaction.channel_id)
            if claimed_by:
                claimer = interaction.guild.get_member(claimed_by)
                await interaction.response.send_message(
                    f"This ticket is claimed by {claimer.mention if claimer else 'another staff member'} — "
                    f"only they or the ticket owner can close it.", ephemeral=True
                )
            else:
                await interaction.response.send_message("Only the ticket owner or support staff can close this.", ephemeral=True)
            return
        embed = discord.Embed(description="Saving transcript and closing in 5 seconds...", color=config.WARNING_COLOR)
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(5)
        await _save_transcript_and_delete(interaction.channel, interaction.guild, closed_by=interaction.user.id)

    # ── Stats ──────────────────────────────────────────────────────────────
    @app_commands.command(name="ticket-stats", description="Show ticket-handling stats for a staff member, or the team leaderboard")
    @app_commands.describe(member="Staff member to check (leave empty for the team leaderboard)")
    async def ticket_stats(self, interaction: discord.Interaction, member: discord.Member = None):
        stats = load_stats()
        gstats = stats.get(str(interaction.guild_id), {})

        if member:
            s = gstats.get(str(member.id), {"claimed": 0, "closed": 0})
            embed = discord.Embed(title=f"Ticket Stats — {member.display_name}", color=config.EMBED_COLOR)
            embed.add_field(name="Claimed", value=str(s.get("claimed", 0)), inline=True)
            embed.add_field(name="Closed", value=str(s.get("closed", 0)), inline=True)
            await interaction.response.send_message(embed=embed)
            return

        ranked = sorted(gstats.items(), key=lambda kv: kv[1].get("closed", 0), reverse=True)[:10]
        if not ranked:
            await interaction.response.send_message(
                embed=discord.Embed(description="No stats yet.", color=config.EMBED_COLOR), ephemeral=True
            )
            return

        lines = []
        for i, (uid, s) in enumerate(ranked, 1):
            m = interaction.guild.get_member(int(uid))
            lines.append(f"{i}. {(m.mention if m else uid)} — closed: {s.get('closed', 0)}, claimed: {s.get('claimed', 0)}")

        embed = discord.Embed(title="Ticket Team Stats", description="\n".join(lines), color=config.EMBED_COLOR)
        await interaction.response.send_message(embed=embed)

    # ─── helper ─────────────────────────────────────────────────────────────
    def _summary_embed(self, title: str, cfg: dict) -> discord.Embed:
        embed = discord.Embed(title=title, color=config.SUCCESS_COLOR)
        embed.add_field(name="Panel channel", value=f"<#{cfg.get('panel_channel_id')}>" if cfg.get("panel_channel_id") else "Not set", inline=True)
        embed.add_field(name="Log channel", value=f"<#{cfg.get('log_channel_id')}>" if cfg.get("log_channel_id") else "None", inline=True)
        embed.add_field(name="Ticket types", value=str(len(cfg.get("types", {}))), inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        return embed


async def setup(bot):
    await bot.add_cog(Tickets(bot))
