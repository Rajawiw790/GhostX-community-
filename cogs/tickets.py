import discord
from discord.ext import commands
from discord import app_commands
from discord.ext import tasks
import config
from datetime import datetime
import asyncio
import db

from cogs import panel_settings
from cogs import emoji_loader

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
# warning + auto-close below. Kept separate from TICKET_COLLECTION (which is
# per-guild config) since this is per-ticket and gets touched much more often.
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


BUTTON_DEFAULTS = {
    "open_label":  "Open Ticket",
    "open_emoji":  "📩",
    "close_label": "Close",
    "close_emoji": "🔒",
    "claim_label": "Claim",
    "claim_emoji": "📋",
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

    # ── Build the ticket embed — the reason the member typed is the whole
    #    point of this message, so it now leads the embed as the description
    #    (bold label + blockquote) instead of being buried under a field.
    #    Opener/role/instructions move down into compact fields. ──
    support_icon = emoji_loader.get("fl_support")
    instructions_text = panel_settings.render(panel_settings.get("ticket_instructions_text")) or (
        "Please write what you need right away instead of waiting for staff to reply first."
    )
    custom_msg = cfg.get("panel_message") or "Our support team will be with you shortly."
    reason_label = panel_settings.get("ticket_reason_label") or "🗒️ Ticket Reason"

    embed = discord.Embed(
        title=f"🎫 Ticket — {interaction.user.display_name}",
        description=f"**{reason_label}**\n>>> {problem_text[:500]}",
        color=config.EMBED_COLOR,
        timestamp=datetime.now(),
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)

    banner_url = cfg.get("banner_url") or ""
    if banner_url:
        embed.set_image(url=banner_url)

    embed.add_field(
        name="👤 Opened by",
        value=f"{interaction.user.mention} • <t:{int(datetime.now().timestamp())}:R>",
        inline=True,
    )
    if support_role:
        embed.add_field(name=f"{support_icon} Assigned role".strip(), value=support_role.mention, inline=True)
    embed.add_field(name="ℹ️ Info", value=f"{instructions_text}\n{custom_msg}"[:600], inline=False)
    embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

    ping_parts = [interaction.user.mention]
    if support_role:
        ping_parts.append(support_role.mention)

    await ticket_channel.send(
        content=" ".join(ping_parts),
        embed=embed,
        view=TicketControlView(),
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
    }
    save_activity(activity)


# ─── Ticket Panel Button (on /ticket setup panel) ──────────────────────────
class TicketCreateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        btn = load_btn()
        button = discord.ui.Button(
            label=btn["open_label"],
            emoji=btn["open_emoji"],
            style=discord.ButtonStyle.primary,
            custom_id="ticket_open"
        )
        button.callback = self.open_ticket
        self.add_item(button)

    async def open_ticket(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ProblemModal())


# ─── Ticket Control Buttons (inside the ticket channel) ────────────────────
class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        btn = load_btn()
        self.claim.label = btn["claim_label"]
        self.claim.emoji = btn["claim_emoji"]
        self.close.label = btn["close_label"]
        self.close.emoji = btn["close_emoji"]
        self.support_panel.label = panel_settings.get("ticket_support_panel_label") or "Support Panel"
        self.support_panel.emoji = panel_settings.get("ticket_support_panel_emoji") or "🛠️"

    @discord.ui.button(label="Claim", emoji="📋", style=discord.ButtonStyle.success, custom_id="ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user has support role or is admin
        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        if not _is_support_staff(interaction.user, cfg):
            await interaction.response.send_message("❌ Only support staff can claim tickets.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📋 Ticket Claimed",
            description=f"This ticket has been claimed by {interaction.user.mention}.",
            color=config.SUCCESS_COLOR,
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

        # Disable the claim button
        button.disabled = True
        button.label = f"Claimed by {interaction.user.display_name}"
        await interaction.message.edit(view=self)

    @discord.ui.button(label="Close", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket_close_btn")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔒 Closing Ticket",
                description="This ticket will be closed and logged in 5 seconds...",
                color=config.WARNING_COLOR
            )
        )
        await asyncio.sleep(5)
        await _save_transcript_and_delete(interaction.channel, interaction.guild)

    @discord.ui.button(label="Support Panel", emoji="🛠️", style=discord.ButtonStyle.secondary, custom_id="ticket_support_panel")
    async def support_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        support_role = interaction.guild.get_role(cfg.get("support_role_id") or 0)

        embed = discord.Embed(
            title="🛠️ Support Panel",
            description=(
                f"{'👥 Support role: ' + support_role.mention if support_role else '⚠️ No support role configured.'}\n\n"
                "**Available commands in this ticket:**\n"
                "`/ticket-add` — add another member to this ticket\n"
                "`/ticket-close` — close this ticket"
            ),
            color=config.EMBED_COLOR
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


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

            import io
            file_obj = discord.File(io.BytesIO(buf), filename=f"transcript-{channel.name}.txt")

            # Find ticket owner from topic
            owner_id = channel.topic
            owner_mention = f"<@{owner_id}>" if owner_id else "Unknown"

            embed = discord.Embed(
                title="📄 Ticket Transcript",
                description=f"**Channel:** #{channel.name}\n**Owner:** {owner_mention}\n**Closed at:** <t:{int(datetime.now().timestamp())}:F>",
                color=config.EMBED_COLOR,
                timestamp=datetime.now()
            )
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
                    embed = discord.Embed(
                        title="⏰ Still waiting on a reply",
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
                        await _save_transcript_and_delete(channel, guild)  # untracks internally
                        activity.pop(ch_key, None)
                        changed = True
            except Exception as e:
                print(f"[Tickets] inactivity check failed for channel {ch_key}: {e}")

        if changed:
            save_activity(activity)

    @check_inactive_tickets.before_loop
    async def before_check_inactive_tickets(self):
        await self.bot.wait_until_ready()

    # ─── /ticket setup — every field is a real picker, nothing to type by hand ──
    @ticket_group.command(name="setup", description="⚙️ Set up the ticket system")
    @app_commands.describe(
        panel_channel="Channel where the ticket panel (Open Ticket button) will be posted",
        category="Category where new ticket channels will be created (optional)",
        support_role="Role that can see and claim tickets (optional)",
        log_channel="Channel where closed ticket transcripts are sent (optional)",
        panel_message="Message shown inside opened tickets (optional)",
        banner_url="Banner image URL for the ticket embed (optional)",
    )
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
        panel_channel: discord.TextChannel,
        category: discord.CategoryChannel = None,
        support_role: discord.Role = None,
        log_channel: discord.TextChannel = None,
        panel_message: str = None,
        banner_url: str = None,
    ):
        cfg = {
            "panel_channel_id": panel_channel.id,
            "category_id": category.id if category else None,
            "support_role_id": support_role.id if support_role else None,
            "log_channel_id": log_channel.id if log_channel else None,
            "panel_message": panel_message or "Our support team will be with you shortly.",
            "banner_url": banner_url or "",
        }
        ts = load_tickets()
        ts[str(interaction.guild_id)] = cfg
        save_tickets(ts)

        panel_embed = discord.Embed(
            title="🎫 Support Tickets",
            description=cfg["panel_message"],
            color=config.EMBED_COLOR
        )
        if cfg["banner_url"]:
            panel_embed.set_image(url=cfg["banner_url"])
        panel_embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

        try:
            await panel_channel.send(embed=panel_embed, view=TicketCreateView())
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to send panel: {e}", ephemeral=True)
            return

        await interaction.response.send_message(embed=self._summary_embed("✅ Ticket System Set Up!", panel_channel, category, support_role, log_channel), ephemeral=True)

    # ─── /ticket update — only fill in what changes ─────────────────────────
    @ticket_group.command(name="update", description="✏️ Update ticket settings — only fill in what you want to change")
    @app_commands.describe(
        panel_channel="New panel channel (optional)",
        category="New ticket category (optional)",
        support_role="New support role (optional)",
        log_channel="New transcript log channel (optional)",
        panel_message="New panel message shown inside tickets (optional)",
        banner_url="New banner image URL (optional)",
    )
    async def ticket_update(
        self,
        interaction: discord.Interaction,
        panel_channel: discord.TextChannel = None,
        category: discord.CategoryChannel = None,
        support_role: discord.Role = None,
        log_channel: discord.TextChannel = None,
        panel_message: str = None,
        banner_url: str = None,
    ):
        ts = load_tickets()
        guild_id = str(interaction.guild_id)
        cfg = ts.get(guild_id)
        if not cfg:
            await interaction.response.send_message("❌ Ticket system not set up yet. Use `/ticket setup` first.", ephemeral=True)
            return

        if panel_channel: cfg["panel_channel_id"] = panel_channel.id
        if category:      cfg["category_id"] = category.id
        if support_role:  cfg["support_role_id"] = support_role.id
        if log_channel:   cfg["log_channel_id"] = log_channel.id
        if panel_message: cfg["panel_message"] = panel_message
        if banner_url is not None: cfg["banner_url"] = banner_url

        ts[guild_id] = cfg
        save_tickets(ts)

        p_ch  = interaction.guild.get_channel(cfg.get("panel_channel_id") or 0)
        cat   = interaction.guild.get_channel(cfg.get("category_id") or 0)
        s_role= interaction.guild.get_role(cfg.get("support_role_id") or 0)
        l_ch  = interaction.guild.get_channel(cfg.get("log_channel_id") or 0)
        await interaction.response.send_message(embed=self._summary_embed("✅ Ticket Settings Updated!", p_ch, cat, s_role, l_ch), ephemeral=True)

    # ─── /ticket remove ──────────────────────────────────────────────────────
    @ticket_group.command(name="remove", description="🗑️ Remove the ticket system setup")
    async def ticket_remove(self, interaction: discord.Interaction):
        ts = load_tickets()
        ts.pop(str(interaction.guild_id), None)
        save_tickets(ts)
        embed = discord.Embed(
            title="🗑️ Ticket System Removed",
            description="The ticket system has been disabled for this server.",
            color=config.ERROR_COLOR
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─── /ticket customize — button labels/emoji + instructions text ───────
    @ticket_group.command(name="customize", description="🎨 Customize ticket button labels/emoji and the instructions text")
    @app_commands.describe(
        open_label="Open-ticket button label (optional)", open_emoji="Open-ticket button emoji (optional)",
        claim_label="Claim button label (optional)", claim_emoji="Claim button emoji (optional)",
        close_label="Close button label (optional)", close_emoji="Close button emoji (optional)",
        instructions_text="Important-instructions text shown in every ticket (optional)",
    )
    async def ticket_customize(
        self,
        interaction: discord.Interaction,
        open_label: str = None, open_emoji: str = None,
        claim_label: str = None, claim_emoji: str = None,
        close_label: str = None, close_emoji: str = None,
        instructions_text: str = None,
    ):
        if not any([open_label, open_emoji, claim_label, claim_emoji, close_label, close_emoji, instructions_text]):
            await interaction.response.send_message("❌ Provide at least one field to change.", ephemeral=True)
            return

        btn = load_btn()
        if open_label:  btn["open_label"] = open_label
        if open_emoji:  btn["open_emoji"] = open_emoji
        if claim_label: btn["claim_label"] = claim_label
        if claim_emoji: btn["claim_emoji"] = claim_emoji
        if close_label: btn["close_label"] = close_label
        if close_emoji: btn["close_emoji"] = close_emoji
        save_btn(btn)

        if instructions_text:
            panel_settings.set_values(ticket_instructions_text=instructions_text)

        embed = discord.Embed(
            title="✅ Ticket Panel Customized",
            description="Changes apply next time `/ticket setup` posts a panel, or to newly opened tickets.",
            color=config.SUCCESS_COLOR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Add member to ticket ──────────────────────────────────────────────
    @app_commands.command(name="ticket-add", description="👤 Add a member to the current ticket")
    @app_commands.describe(member="The member to add")
    async def ticket_add(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.channel.name.startswith("ticket-"):
            await interaction.response.send_message("❌ This command only works inside a ticket channel.", ephemeral=True)
            return
        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        if not _is_support_staff(interaction.user, cfg):
            await interaction.response.send_message("❌ Support staff only.", ephemeral=True)
            return
        await interaction.channel.set_permissions(member, read_messages=True, send_messages=True)
        embed = discord.Embed(
            title="✅ Member Added",
            description=f"{member.mention} has been added to this ticket.",
            color=config.SUCCESS_COLOR
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

    # ── Close ticket by command ───────────────────────────────────────────
    @app_commands.command(name="ticket-close", description="🔒 Close the current ticket")
    async def ticket_close(self, interaction: discord.Interaction):
        if not interaction.channel.name.startswith("ticket-"):
            await interaction.response.send_message("❌ This command only works inside a ticket channel.", ephemeral=True)
            return
        ts = load_tickets()
        cfg = ts.get(str(interaction.guild_id), {})
        is_owner = interaction.channel.topic == str(interaction.user.id)
        if not (_is_support_staff(interaction.user, cfg) or is_owner):
            await interaction.response.send_message("❌ Only the ticket owner or support staff can close this.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🔒 Closing Ticket",
            description="Saving transcript and closing in 5 seconds...",
            color=config.WARNING_COLOR
        )
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(5)
        await _save_transcript_and_delete(interaction.channel, interaction.guild)

    # ─── helper ─────────────────────────────────────────────────────────────
    def _summary_embed(self, title, panel_channel, category, support_role, log_channel) -> discord.Embed:
        embed = discord.Embed(title=title, color=config.SUCCESS_COLOR)
        embed.add_field(name="📢 Panel Channel", value=panel_channel.mention if panel_channel else "❌ Not set", inline=True)
        embed.add_field(name="🗂️ Category",      value=category.mention if category else "None", inline=True)
        embed.add_field(name="🏷️ Support Role",  value=support_role.mention if support_role else "None", inline=True)
        embed.add_field(name="📄 Log Channel",   value=log_channel.mention if log_channel else "None", inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        return embed


async def setup(bot):
    await bot.add_cog(Tickets(bot))
