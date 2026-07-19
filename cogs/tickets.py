import discord
from discord.ext import commands
from discord import app_commands
import config
from datetime import datetime
import asyncio
import db

from cogs import panel_settings
from cogs import emoji_loader

TICKET_COLLECTION = "tickets"
BUTTON_COLLECTION = "ticket_buttons"

# ─── Storage helpers ────────────────────────────────────────────────────────
def load_tickets() -> dict:
    return db.load(TICKET_COLLECTION)

def save_tickets(data: dict):
    db.save(TICKET_COLLECTION, data)


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

    # ── Build the ticket embed — kept short on purpose: opener/time on one
    #    line, the reason on another, everything else folded into a single
    #    short description instead of piling up extra fields. ──
    support_icon = emoji_loader.get("fl_support")
    instructions_text = panel_settings.render(panel_settings.get("ticket_instructions_text")) or (
        "Please write what you need right away instead of waiting for staff to reply first."
    )
    custom_msg = cfg.get("panel_message") or "Our support team will be with you shortly."
    desc_lines = [instructions_text, custom_msg]
    if support_role:
        desc_lines.insert(0, f"{support_icon} {support_role.mention}".strip())

    embed = discord.Embed(
        title=f"🎫 Ticket — {interaction.user.display_name}",
        description="\n".join(desc_lines)[:600],
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
        inline=False,
    )
    reason_label = panel_settings.get("ticket_reason_label") or "🗒️ Ticket Reason"
    embed.add_field(name=reason_label, value=f">>> {problem_text[:500]}", inline=False)
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
        support_role_id = cfg.get("support_role_id")
        is_staff = interaction.user.guild_permissions.manage_channels
        if support_role_id:
            support_role = interaction.guild.get_role(support_role_id)
            if support_role and support_role in interaction.user.roles:
                is_staff = True
        if not is_staff:
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
    @app_commands.default_permissions(manage_channels=True)
    async def ticket_add(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.channel.name.startswith("ticket-"):
            await interaction.response.send_message("❌ This command only works inside a ticket channel.", ephemeral=True)
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
    @app_commands.default_permissions(manage_channels=True)
    async def ticket_close(self, interaction: discord.Interaction):
        if not interaction.channel.name.startswith("ticket-"):
            await interaction.response.send_message("❌ This command only works inside a ticket channel.", ephemeral=True)
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
