import discord
from discord.ext import commands
from discord import app_commands
from discord.ext import tasks
import config
from datetime import datetime
import asyncio
import io
import db

from cogs import panel_settings

TICKET_COLLECTION = "tickets"
BUTTON_COLLECTION = "ticket_buttons"
ACTIVITY_COLLECTION = "ticket_activity"

# No staff reply within this long → send one warning ping to the support role.
INACTIVITY_SECONDS = 5 * 3600
# Still nothing after the warning → auto-close the ticket.
CLOSE_GRACE_SECONDS = 30 * 60

# ─── Storage helpers ────────────────────────────────────────────────────────
def load_tickets() -> dict:
    return db.load(TICKET_COLLECTION)

def save_tickets(data: dict):
    db.save(TICKET_COLLECTION, data)


# Per-ticket activity tracking, keyed by channel id — powers the 5h inactivity
# warning + auto-close below, AND (once claimed) who's allowed to close the
# ticket. Kept separate from TICKET_COLLECTION (which is per-guild config)
# since this is per-ticket and gets touched much more often.
def load_activity() -> dict:
    return db.load(ACTIVITY_COLLECTION)

def save_activity(data: dict):
    db.save(ACTIVITY_COLLECTION, data)

def _untrack_ticket(channel_id: int):
    activity = load_activity()
    if activity.pop(str(channel_id), None) is not None:
        save_activity(activity)


def _is_support_staff(member: discord.Member, cfg: dict) -> bool:
    """True for anyone who should be able to act as staff on a ticket:
    Manage Channels permission, or the guild's configured support role."""
    if member.guild_permissions.manage_channels:
        return True
    support_role_id = cfg.get("support_role_id")
    if support_role_id:
        return any(role.id == support_role_id for role in member.roles)
    return False


def _get_claimed_by(channel_id: int) -> int | None:
    activity = load_activity()
    rec = activity.get(str(channel_id))
    return rec.get("claimed_by") if rec else None


def _can_close_ticket(member: discord.Member, channel: discord.TextChannel, cfg: dict) -> bool:
    """Who's allowed to close a ticket:
    - Always: the ticket owner (channel.topic == their id).
    - Unclaimed ticket: any support staff (old behavior).
    - Claimed ticket: ONLY the staff member who claimed it (support staff who
      didn't claim it can no longer close someone else's claimed ticket)."""
    is_owner = channel.topic == str(member.id)
    if is_owner:
        return True

    claimed_by = _get_claimed_by(channel.id)
    if claimed_by:
        return member.id == claimed_by

    return _is_support_staff(member, cfg)


# ── Discord only allows these 4 button colors (no custom hex) ──────────────
STYLE_MAP = {
    "primary": discord.ButtonStyle.primary,      # Blurple
    "secondary": discord.ButtonStyle.secondary,  # Gray
    "success": discord.ButtonStyle.success,      # Green
    "danger": discord.ButtonStyle.danger,        # Red
}

BUTTON_DEFAULTS = {
    "open_label":  "Open Ticket",
    "open_emoji":  "📩",
    "open_style":  "primary",
    "close_label": "Close",
    "close_emoji": "🔒",
    "claim_label": "Claim",
    "claim_emoji": "📋",
    "add_label":   "Add Member",
    "add_emoji":   "➕",
}

def load_btn() -> dict:
    data = db.load_doc(BUTTON_COLLECTION)
    return {**BUTTON_DEFAULTS, **data}

def save_btn(data: dict):
    db.save_doc(BUTTON_COLLECTION, data)


# ─── Problem Modal ──────────────────────────────────────────────────────────
class ProblemModal(discord.ui.Modal, title="📝 Describe your issue"):
    problem = discord.ui.TextInput(
        label="What do you need help with?",
        style=discord.TextStyle.paragraph,
        placeholder="Describe your issue clearly so the support team can help you quickly...",
        min_length=5,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await _create_ticket(interaction, self.problem.value)


# ─── Create ticket channel ──────────────────────────────────────────────────
async def _create_ticket(interaction: discord.Interaction, problem_text: str):
    ts = load_tickets()
    cfg = ts.get(str(interaction.guild_id))
    if not cfg:
        await interaction.followup.send(
            "❌ Ticket system is not configured! Use `/ticket setup`.", ephemeral=True
        )
        return

    category_id = cfg.get("category_id")
    category = interaction.guild.get_channel(category_id) if category_id else None

    # Check for existing open ticket
    if category:
        for channel in category.text_channels:
            if channel.topic == str(interaction.user.id):
                await interaction.followup.send(
                    f"⚠️ You already have an open ticket: {channel.mention}", ephemeral=True
                )
                return

    # Start from the category's own overwrites (e.g. a staff/admin role that
    # already has access at the category level) so the ticket channel inherits
    # them, then layer the required ticket-specific permissions on top.
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
    support_role_id = cfg.get("support_role_id")
    if support_role_id:
        support_role = interaction.guild.get_role(support_role_id)
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(
                read_messages=True, send_messages=True
            )

    ch_name = f"ticket-{interaction.user.name}".lower().replace(" ", "-")[:80]

    try:
        ticket_channel = await interaction.guild.create_text_channel(
            name=ch_name,
            topic=str(interaction.user.id),
            category=category,
            overwrites=overwrites,
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to create ticket channel: {e}", ephemeral=True)
        return

    # ── Build the ticket panel (Components V2) ──────────────────────────
    # NOTE: this note is intentionally SHORT and SEPARATE from the panel's
    # "Need help? / Please: ..." instructions block — it used to reuse
    # panel_message / ticket_instructions_text (and even the panel banner),
    # which duplicated the whole panel post inside every opened ticket.
    note_text = cfg.get("ticket_note") or "Our team will be with you shortly."
    reason_label = panel_settings.get("ticket_reason_label") or "Ticket Reason"
    opened_ts = int(datetime.now().timestamp())

    ping_parts = [interaction.user.mention]
    if support_role:
        ping_parts.append(support_role.mention)

    # NOTE: Components V2 messages (LayoutView) cannot carry a `content` field —
    # Discord rejects the request if you try. So the ping line has to live
    # inside a TextDisplay component instead; allowed_mentions still governs
    # whether it actually notifies.
    view = TicketControlView(
        owner=interaction.user,
        support_role=support_role,
        reason_label=reason_label,
        problem_text=problem_text,
        note_text=note_text,
        opened_ts=opened_ts,
        ping_line=" ".join(ping_parts),
    )

    await ticket_channel.send(
        view=view,
        allowed_mentions=discord.AllowedMentions(users=True, roles=True),
    )
    await interaction.followup.send(
        f"✅ Your ticket has been created: {ticket_channel.mention}", ephemeral=True
    )

    # Start the inactivity clock for this ticket (see _check_inactive_tickets).
    activity = load_activity()
    activity[str(ticket_channel.id)] = {
        "guild_id": interaction.guild_id,
        "owner_id": interaction.user.id,
        "opened_at": datetime.now().timestamp(),
        "last_reply_at": None,
        "warned": False,
        "warned_at": None,
        "claimed_by": None,
    }
    save_activity(activity)


# ─── Ticket Panel Button (on /ticket setup panel) — Components V2 ──────────
class TicketCreateView(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        btn = load_btn()

        container = discord.ui.Container(accent_colour=config.EMBED_COLOR)
        container.add_item(discord.ui.TextDisplay(
            f"## 🎫 {config.BOT_NAME} — Support\n"
            "Need help? Press the button below to open a private ticket "
            "with our support team."
        ))
        container.add_item(discord.ui.Separator())

        row = discord.ui.ActionRow()
        button = discord.ui.Button(
            label=btn["open_label"],
            emoji=btn["open_emoji"],
            style=STYLE_MAP.get(btn.get("open_style", "primary"), discord.ButtonStyle.primary),
            custom_id="ticket_open",
        )
        button.callback = self.open_ticket
        row.add_item(button)
        container.add_item(row)

        self.add_item(container)

    async def open_ticket(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ProblemModal())


# ─── Add Member select (used inside the ticket control panel) ─────────────
class AddMemberSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(
            placeholder="اختار العضو لي بغيتي تزيدو للتذكرة...",
            min_values=1,
            max_values=1,
            custom_id="ticket_add_member_select",
        )

    async def callback(self, interaction: discord.Interaction):
        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        if not _is_support_staff(interaction.user, cfg):
            await interaction.response.send_message(
                "❌ Only support staff can add members to a ticket.", ephemeral=True
            )
            return

        member = self.values[0]
        try:
            await interaction.channel.set_permissions(
                member, read_messages=True, send_messages=True, attach_files=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to add member: {e}", ephemeral=True)
            return

        await interaction.response.send_message(
            f"➕ {member.mention} has been added to this ticket by {interaction.user.mention}.",
            allowed_mentions=discord.AllowedMentions(users=True),
        )


# ─── Ticket Control Panel (inside the ticket channel) — Components V2 ─────
class TicketControlView(discord.ui.LayoutView):
    def __init__(self, owner: discord.Member = None, support_role: discord.Role = None,
                 reason_label: str = "Ticket Reason", problem_text: str = "",
                 note_text: str = "", opened_ts: int = None, claimed_by: int = None,
                 ping_line: str = None):
        super().__init__(timeout=None)
        btn = load_btn()
        self.owner = owner
        self.support_role = support_role

        container = discord.ui.Container(accent_colour=config.EMBED_COLOR)

        # Components V2 messages can't use `content` for pings, so the mention
        # line (owner + support role) is rendered as its own TextDisplay at
        # the top of the container instead. allowed_mentions on the send()
        # call still controls whether this actually notifies anyone.
        if ping_line:
            container.add_item(discord.ui.TextDisplay(ping_line))

        # ── Header section with the owner's avatar as a thumbnail ──
        header_text = discord.ui.TextDisplay(
            f"## 🎫 Ticket — {owner.display_name if owner else 'Unknown'}\n"
            f"**{reason_label}**\n>>> {problem_text[:350] if problem_text else '—'}"
        )
        if owner:
            container.add_item(discord.ui.Section(
                header_text,
                accessory=discord.ui.Thumbnail(media=owner.display_avatar.url),
            ))
        else:
            container.add_item(header_text)

        container.add_item(discord.ui.Separator())

        opened_line = f"{owner.mention if owner else '—'} • " + (
            f"<t:{opened_ts}:R>" if opened_ts else "—"
        )
        if support_role:
            opened_line += f" • {support_role.mention}"

        status_line = (
            f"🔒 Claimed by <@{claimed_by}>" if claimed_by else "🔓 Not claimed yet"
        )

        container.add_item(discord.ui.TextDisplay(
            f"**Opened by:** {opened_line}\n"
            f"**Note:** {note_text[:200] if note_text else '—'}\n"
            f"**Status:** {status_line}"
        ))
        container.add_item(discord.ui.Separator())

        # ── Action buttons row ──
        row = discord.ui.ActionRow()

        self.claim_button = discord.ui.Button(
            label=(f"Claimed by {self._member_name(claimed_by)}" if claimed_by else btn["claim_label"]),
            emoji=btn["claim_emoji"],
            style=discord.ButtonStyle.success,
            custom_id="ticket_claim",
            disabled=bool(claimed_by),
        )
        self.claim_button.callback = self.claim
        row.add_item(self.claim_button)

        self.close_button = discord.ui.Button(
            label=btn["close_label"],
            emoji=btn["close_emoji"],
            style=discord.ButtonStyle.danger,
            custom_id="ticket_close_btn",
        )
        self.close_button.callback = self.close
        row.add_item(self.close_button)

        self.add_member_button = discord.ui.Button(
            label=btn["add_label"],
            emoji=btn["add_emoji"],
            style=discord.ButtonStyle.secondary,
            custom_id="ticket_add_member_btn",
        )
        self.add_member_button.callback = self.open_add_member
        row.add_item(self.add_member_button)

        self.support_panel_button = discord.ui.Button(
            label=panel_settings.get("ticket_support_panel_label") or "Support Panel",
            emoji=panel_settings.get("ticket_support_panel_emoji") or "🛠️",
            style=discord.ButtonStyle.secondary,
            custom_id="ticket_support_panel",
        )
        self.support_panel_button.callback = self.support_panel
        row.add_item(self.support_panel_button)

        container.add_item(row)
        self.add_item(container)

    @staticmethod
    def _member_name(user_id):
        return f"<@{user_id}>" if user_id else "?"

    async def claim(self, interaction: discord.Interaction):
        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        if not _is_support_staff(interaction.user, cfg):
            await interaction.response.send_message("❌ Only support staff can claim tickets.", ephemeral=True)
            return

        activity = load_activity()
        ch_key = str(interaction.channel_id)
        rec = activity.get(ch_key)
        if rec and rec.get("claimed_by") and rec["claimed_by"] != interaction.user.id:
            claimer = interaction.guild.get_member(rec["claimed_by"])
            await interaction.response.send_message(
                f"❌ Already claimed by {claimer.mention if claimer else 'another staff member'}.", ephemeral=True
            )
            return

        if not rec:
            rec = {
                "guild_id": interaction.guild_id,
                "owner_id": int(interaction.channel.topic) if interaction.channel.topic and interaction.channel.topic.isdigit() else None,
                "opened_at": datetime.now().timestamp(),
                "last_reply_at": None,
                "warned": False,
                "warned_at": None,
            }
        rec["claimed_by"] = interaction.user.id
        activity[ch_key] = rec
        save_activity(activity)

        # Lock the claim button on the panel itself
        self.claim_button.disabled = True
        self.claim_button.label = f"Claimed by {interaction.user.display_name}"
        await interaction.response.edit_message(view=self)

        await interaction.followup.send(
            f"📋 Ticket claimed by {interaction.user.mention} — "
            f"only they or the ticket owner can close it from now on.",
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    async def close(self, interaction: discord.Interaction):
        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        if not _can_close_ticket(interaction.user, interaction.channel, cfg):
            claimed_by = _get_claimed_by(interaction.channel_id)
            if claimed_by:
                claimer = interaction.guild.get_member(claimed_by)
                await interaction.response.send_message(
                    f"❌ This ticket is claimed by {claimer.mention if claimer else 'another staff member'} — "
                    f"only they or the ticket owner can close it.", ephemeral=True
                )
            else:
                await interaction.response.send_message("❌ Only support staff or the ticket owner can close this.", ephemeral=True)
            return

        for item in (self.claim_button, self.close_button, self.add_member_button, self.support_panel_button):
            item.disabled = True
        await interaction.response.edit_message(view=self)

        await interaction.followup.send(
            "🔒 **Closing Ticket** — this ticket will be closed and logged in 5 seconds..."
        )
        await asyncio.sleep(5)
        await _save_transcript_and_delete(interaction.channel, interaction.guild)

    async def open_add_member(self, interaction: discord.Interaction):
        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        if not _is_support_staff(interaction.user, cfg):
            await interaction.response.send_message("❌ Only support staff can add members.", ephemeral=True)
            return

        picker = discord.ui.LayoutView(timeout=120)
        container = discord.ui.Container(accent_colour=config.EMBED_COLOR)
        container.add_item(discord.ui.TextDisplay("### ➕ Add a member to this ticket"))
        row = discord.ui.ActionRow()
        row.add_item(AddMemberSelect())
        container.add_item(row)
        picker.add_item(container)

        await interaction.response.send_message(view=picker, ephemeral=True)

    async def support_panel(self, interaction: discord.Interaction):
        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        support_role = interaction.guild.get_role(cfg.get("support_role_id") or 0)
        claimed_by = _get_claimed_by(interaction.channel_id)
        claimer = interaction.guild.get_member(claimed_by) if claimed_by else None

        view = discord.ui.LayoutView(timeout=None)
        container = discord.ui.Container(accent_colour=config.EMBED_COLOR)
        container.add_item(discord.ui.TextDisplay(
            "### 🛠️ Support Panel\n"
            f"{'👥 Support role: ' + support_role.mention if support_role else '⚠️ No support role configured.'}\n"
            f"{'🔒 Claimed by: ' + claimer.mention if claimer else '🔓 Not claimed yet.'}\n\n"
            "**Available commands in this ticket:**\n"
            "`/ticket-add` — add another member to this ticket\n"
            "`/ticket-close` — close this ticket"
        ))
        view.add_item(container)
        await interaction.response.send_message(view=view, ephemeral=True)


# ─── Transcript save and channel delete ─────────────────────────────────────
async def _save_transcript_and_delete(channel: discord.TextChannel, guild: discord.Guild):
    _untrack_ticket(channel.id)

    ts = load_tickets()
    cfg = ts.get(str(guild.id), {})
    log_ch_id = cfg.get("log_channel_id")

    if log_ch_id:
        log_channel = guild.get_channel(log_ch_id)
        if log_channel:
            # Build transcript text
            lines = []
            async for msg in channel.history(limit=500, oldest_first=True):
                ts_time = msg.created_at.strftime("%Y-%m-%d %H:%M")
                content = msg.content or "[embed/attachment]"
                lines.append(f"[{ts_time}] {msg.author.display_name}: {content}")

            transcript_text = "\n".join(lines) if lines else "No messages."
            buf = transcript_text.encode("utf-8")
            file_obj = discord.File(io.BytesIO(buf), filename=f"transcript-{channel.name}.txt")

            # Find ticket owner from topic
            owner_id = channel.topic
            owner_mention = f"<@{owner_id}>" if owner_id else "Unknown"

            log_view = discord.ui.LayoutView(timeout=None)
            log_container = discord.ui.Container(accent_colour=config.EMBED_COLOR)
            log_container.add_item(discord.ui.TextDisplay(
                "### 📄 Ticket Transcript\n"
                f"**Channel:** #{channel.name}\n"
                f"**Owner:** {owner_mention}\n"
                f"**Closed at:** <t:{int(datetime.now().timestamp())}:F>"
            ))
            log_view.add_item(log_container)
            await log_channel.send(view=log_view, file=file_obj)

    try:
        await channel.delete()
    except Exception:
        pass


# ─── Tickets Cog ─────────────────────────────────────────────────────────────
class Tickets(commands.Cog):
    ticket_group = app_commands.Group(
        name="ticket",
        description="🎫 Manage the ticket system",
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(self, bot):
        self.bot = bot
        self.check_inactive_tickets.start()

    async def cog_unload(self):
        self.check_inactive_tickets.cancel()

    # ── Any message a support staff member sends inside a tracked ticket
    #    resets that ticket's inactivity clock. ──
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

    # ── Background task — checks every 10 min for tickets support hasn't
    #    replied to. 5h quiet → warning ping. 30 more min quiet → auto-close. ──
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
                    support_role = guild.get_role(cfg.get("support_role_id") or 0)

                    warn_view = discord.ui.LayoutView(timeout=None)
                    warn_container = discord.ui.Container(accent_colour=config.WARNING_COLOR)
                    # Ping line goes inside the component text — `content` is
                    # not allowed alongside a Components V2 view.
                    warn_text = "### ⏰ Still waiting on a reply\n"
                    if support_role:
                        warn_text = f"{support_role.mention}\n" + warn_text
                    warn_text += (
                        f"No one from support has answered this ticket in over "
                        f"**{INACTIVITY_SECONDS // 3600} hours**. It will close "
                        f"automatically in **{CLOSE_GRACE_SECONDS // 60} minutes** "
                        f"if it stays quiet."
                    )
                    warn_container.add_item(discord.ui.TextDisplay(warn_text))
                    warn_view.add_item(warn_container)

                    try:
                        await channel.send(
                            view=warn_view,
                            allowed_mentions=discord.AllowedMentions(roles=True),
                        )
                    except Exception:
                        pass
                    rec["warned"] = True
                    rec["warned_at"] = now
                    activity[ch_key] = rec
                    changed = True
                    continue

                # Already warned — check the close grace period
                warned_at = rec.get("warned_at") or now
                last_since_warn = rec.get("last_reply_at") or warned_at
                if last_since_warn > warned_at:
                    # Staff replied after the warning — reset
                    rec["warned"] = False
                    rec["warned_at"] = None
                    activity[ch_key] = rec
                    changed = True
                    continue

                if now - warned_at >= CLOSE_GRACE_SECONDS:
                    try:
                        close_view = discord.ui.LayoutView(timeout=None)
                        close_container = discord.ui.Container(accent_colour=config.WARNING_COLOR)
                        close_container.add_item(discord.ui.TextDisplay(
                            "### 🔒 Auto-closing ticket\n"
                            "This ticket had no support reply and is being closed automatically."
                        ))
                        close_view.add_item(close_container)
                        await channel.send(view=close_view)
                    except Exception:
                        pass
                    await _save_transcript_and_delete(channel, guild)
                    activity.pop(ch_key, None)
                    changed = True

            except Exception:
                continue

        if changed:
            save_activity(activity)

    @check_inactive_tickets.before_loop
    async def before_check_inactive_tickets(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Tickets(bot))
