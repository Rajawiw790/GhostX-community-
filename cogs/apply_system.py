"""
Unified Application System — Ghostx Community
Professional NordRP-style apply panels.
  /setup apply kind:staff     apply_channel review_channel role reviewer_role banner_url
  /setup apply kind:whitelist apply_channel review_channel role reviewer_role banner_url
"""
import discord
from discord.ext import commands
from discord import app_commands
import config
import db
from datetime import datetime

APPLY_COLLECTION = "apply_settings"

KIND_LABELS = {
    "staff": "📋 Staff Application",
    "whitelist": "🎮 Whitelist Application",
}

KIND_TITLE = {
    "staff": "Staff",
    "whitelist": "Whitelist",
}

DEFAULT_CONDITIONS = {
    "staff": [
        "You must be active in the community.",
        "Good knowledge of server rules and standard etiquette.",
        "Ability to handle high-pressure situations calmly.",
        "No recent serious punishments or toxic behavior.",
        "Minimum age of 15 years old.",
    ],
    "whitelist": [
        "You must read all server rules before applying.",
        "Good understanding of RolePlay basics (NLR, RDM, PowerGaming).",
        "You must have a realistic character backstory ready.",
        "No recent bans or serious punishments on record.",
        "You must be active and serious about RolePlay.",
    ],
}

DEFAULT_QUESTIONS = {
    "staff": [
        "What is your name and age?",
        "How many hours per day can you dedicate to the server?",
        "Do you have previous moderation experience? Explain.",
        "Why do you want to join the staff team?",
        "How would you handle a member who breaks the rules?",
    ],
    "whitelist": [
        "What is your real name and age?",
        "What is your in-game character name?",
        "What do you know about our RolePlay rules (NLR, RDM, PowerGaming)?",
        "Tell us your character's backstory.",
        "Is your character Legal or Illegal, and why?",
    ],
}


# ─── Storage helpers ─────────────────────────────────────────────────────────
def load_apply() -> dict:
    return db.load(APPLY_COLLECTION)


def save_apply(data: dict):
    db.save(APPLY_COLLECTION, data)


def get_kind_cfg(guild_id: int, kind: str) -> dict:
    data = load_apply()
    return data.get(str(guild_id), {}).get(kind, {})


def set_kind_cfg(guild_id: int, kind: str, cfg: dict):
    data = load_apply()
    guild_key = str(guild_id)
    data.setdefault(guild_key, {})
    data[guild_key][kind] = cfg
    save_apply(data)


_sessions: dict[int, dict] = {}


def _split_legal_question(questions: list[str]):
    """If one of the questions asks whether the character is Legal/Illegal,
    pull it out so it can be answered with buttons instead of free text.
    Returns (text_questions, legal_question_or_None)."""
    for i, q in enumerate(questions):
        ql = q.lower()
        if "legal" in ql and "illegal" in ql:
            remaining = questions[:i] + questions[i + 1:]
            return remaining, q
    return questions, None


class LegalIllegalView(discord.ui.View):
    """Shown after the text modal, for the one question that asks Legal vs Illegal."""

    def __init__(self, kind: str, text_questions: list[str], text_answers: list[str], legal_question: str):
        super().__init__(timeout=180)
        self.kind = kind
        self.text_questions = text_questions
        self.text_answers = text_answers
        self.legal_question = legal_question

    async def _finish(self, interaction: discord.Interaction, choice: str):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(
            content=f"**{self.legal_question}**\nSelected: **{choice}**",
            view=self,
        )
        full_questions = self.text_questions + [self.legal_question]
        full_answers = self.text_answers + [choice]
        await _send_to_review(interaction, self.kind, full_questions, full_answers)

    @discord.ui.button(label="Legal", emoji="⚖️", style=discord.ButtonStyle.success)
    async def legal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, "Legal")

    @discord.ui.button(label="Illegal", emoji="🚫", style=discord.ButtonStyle.danger)
    async def illegal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, "Illegal")


# ══════════════════════════════════════════════════════════════════════════
#  Applicant-facing: dynamic question modal
# ══════════════════════════════════════════════════════════════════════════
def build_apply_modal(kind: str, questions: list[str]):
    fields = {}
    for i, q in enumerate(questions[:5]):
        fields[f"a{i}"] = discord.ui.TextInput(
            label=q[:45],
            style=discord.TextStyle.paragraph if i >= 2 else discord.TextStyle.short,
            placeholder="Type your answer here...",
            max_length=500,
            required=True,
        )

    async def on_submit(self, interaction: discord.Interaction):
        answers = [getattr(self, f"a{i}").value for i in range(len(questions))]
        await _send_to_review(interaction, kind, questions, answers)

    title = f"📋 {KIND_LABELS.get(kind, kind.title())}"[:45]
    attrs = {"__discord_ui_modal__": True, "title": title, "on_submit": on_submit}
    attrs.update(fields)
    ModalClass = type("ApplyModal", (discord.ui.Modal,), attrs)
    return ModalClass


def build_apply_modal_with_choice(kind: str, text_questions: list[str], legal_question: str):
    """Same as build_apply_modal, but the Legal/Illegal question is answered
    afterwards with two buttons instead of being a text field here."""
    fields = {}
    for i, q in enumerate(text_questions[:5]):
        fields[f"a{i}"] = discord.ui.TextInput(
            label=q[:45],
            style=discord.TextStyle.paragraph if i >= 2 else discord.TextStyle.short,
            placeholder="Type your answer here...",
            max_length=500,
            required=True,
        )

    async def on_submit(self, interaction: discord.Interaction):
        answers = [getattr(self, f"a{i}").value for i in range(len(text_questions))]
        await interaction.response.send_message(
            content=f"**{legal_question}**\nChoose one:",
            view=LegalIllegalView(kind, text_questions, answers, legal_question),
            ephemeral=True,
        )

    title = f"📋 {KIND_LABELS.get(kind, kind.title())}"[:45]
    attrs = {"__discord_ui_modal__": True, "title": title, "on_submit": on_submit}
    attrs.update(fields)
    ModalClass = type("ApplyModal", (discord.ui.Modal,), attrs)
    return ModalClass


async def _send_to_review(interaction: discord.Interaction, kind: str, questions: list, answers: list):
    cfg = get_kind_cfg(interaction.guild_id, kind)
    review_id = cfg.get("review_channel_id")
    review_ch = interaction.guild.get_channel(review_id) if review_id else None
    if not review_ch:
        await interaction.response.send_message(
            "❌ The review channel isn't configured yet. Contact an admin.", ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"{KIND_LABELS.get(kind, kind.title())} — New Application",
        description=(
            f"**Applicant:** {interaction.user.mention} (`{interaction.user.display_name}`)\n"
            f"ID: `{interaction.user.id}`"
        ),
        color=config.WARNING_COLOR,
        timestamp=datetime.now()
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    for i, (q, a) in enumerate(zip(questions, answers), 1):
        embed.add_field(name=f"{i}. {q[:50]}", value=a or "—", inline=False)
    embed.add_field(
        name="Account Age",
        value=f"<t:{int(interaction.user.created_at.timestamp())}:R>",
        inline=True
    )
    if interaction.user.joined_at:
        embed.add_field(
            name="Joined Server",
            value=f"<t:{int(interaction.user.joined_at.timestamp())}:R>",
            inline=True
        )
    embed.set_footer(text=f"kind:{kind} | {config.BOT_NAME} | Dev: {config.DEVELOPER}")

    view = ApplyReviewView(kind=kind, applicant_id=interaction.user.id)
    await review_ch.send(embed=embed, view=view)

    confirm = discord.Embed(
        title="✅ Application Sent!",
        description="📨 Your application reached the review team. You'll get a DM once it's decided. 📬",
        color=config.SUCCESS_COLOR
    )
    confirm.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
    await interaction.response.send_message(embed=confirm, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════
#  Applicant-facing: the whole apply card — Components V2 (Container)
#  ONE combined message: title + conditions + notice + banner + footer/button
#  all inside the same card, no separate embed+view.
# ══════════════════════════════════════════════════════════════════════════
BUTTON_STYLES = {
    "grey": discord.ButtonStyle.secondary,
    "gray": discord.ButtonStyle.secondary,
    "blue": discord.ButtonStyle.primary,
    "blurple": discord.ButtonStyle.primary,
    "green": discord.ButtonStyle.success,
    "red": discord.ButtonStyle.danger,
}


class ApplyButtonView(discord.ui.LayoutView):
    """Persistent — one instance per (guild, kind), rebuilt from cfg.
    NOTE: constructor is now ApplyButtonView(kind, cfg) — if your startup
    code re-registers persistent views (e.g. in on_ready/setup_hook), update
    that call to pass cfg too: ApplyButtonView(kind, get_kind_cfg(guild_id, kind))
    """
    def __init__(self, kind: str, cfg: dict):
        super().__init__(timeout=None)
        self.kind = kind

        title = cfg.get("title") or f"{config.SERVER_NAME} — {KIND_LABELS.get(kind, kind.title())}"
        conditions = cfg.get("conditions") or DEFAULT_CONDITIONS.get(kind, [])
        banner_url = cfg.get("banner_url")

        default_label = "Staff Application" if kind == "staff" else "Apply for Whitelist"
        button_label = cfg.get("button_label") or default_label
        button_emoji = cfg.get("button_emoji") or "↗️"
        button_style = BUTTON_STYLES.get((cfg.get("button_style") or "grey").lower(), discord.ButtonStyle.secondary)

        conditions_text = "\n".join(f"{i}. {c}" for i, c in enumerate(conditions, 1))
        default_description = (
            f"**Before applying** to join the **{config.SERVER_NAME}** "
            f"{'Staff Team' if kind == 'staff' else 'Whitelist'}, "
            f"make sure you meet the following conditions :"
        )
        description = cfg.get("description") or default_description
        intro_text = f"# {title}\n\n{description}\n\n{conditions_text}"
        notice_text = cfg.get("notice_text") or (
            "> ⚠️ **Important Notice :**\n"
            "> Please fill out the form honestly. Any fake information or "
            "plagiarized answers will lead to an immediate denial and a "
            "permanent blacklist from the recruitment."
        )
        footer_text = cfg.get("footer_text") or f"With love, **{config.SERVER_NAME}** Team."

        btn = discord.ui.Button(
            label=button_label,
            emoji=button_emoji if button_emoji else None,
            style=button_style,
            custom_id=f"apply_open_{kind}",
        )
        btn.callback = self.apply_click

        items = [
            discord.ui.TextDisplay(intro_text),
            discord.ui.TextDisplay(notice_text),
        ]
        if banner_url:
            items.append(discord.ui.Separator())
            items.append(discord.ui.MediaGallery(discord.MediaGalleryItem(banner_url)))
        items.append(discord.ui.Separator())
        # Section = text on the left, accessory (the button) lined up on the
        # right, on the SAME row — this is what puts the button next to the
        # footer line inside the card, exactly like the NordRP panel.
        items.append(discord.ui.Section(discord.ui.TextDisplay(footer_text), accessory=btn))

        container = discord.ui.Container(*items, accent_color=0x3B82F6)
        self.add_item(container)

    async def apply_click(self, interaction: discord.Interaction):
        cfg = get_kind_cfg(interaction.guild_id, self.kind)
        role_id = cfg.get("role_id")
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role and role in interaction.user.roles:
                await interaction.response.send_message("⚠️ You already have this role!", ephemeral=True)
                return
        questions = cfg.get("questions") or DEFAULT_QUESTIONS.get(self.kind, [])
        text_questions, legal_question = _split_legal_question(questions)
        if legal_question:
            ModalClass = build_apply_modal_with_choice(self.kind, text_questions, legal_question)
        else:
            ModalClass = build_apply_modal(self.kind, questions)
        await interaction.response.send_modal(ModalClass())


# ══════════════════════════════════════════════════════════════════════════
#  DM notifications — Components V2 card (accent bar + separators), instead
#  of a plain embed, so accept/reject/ask DMs match the branded panel look.
# ══════════════════════════════════════════════════════════════════════════
class DecisionCardView(discord.ui.LayoutView):
    """One-off card used only for DMs — not persistent, no buttons.

    icon         — a single emoji shown next to the heading (✅ / 🚫 / 💬 ...)
    heading      — e.g. "Whitelist Application Approved"
    body_lines   — each becomes its own line under the heading
                   (use "• **Label** : value" for the bullet rows)
    accent_color — the color of the left accent bar
    """

    def __init__(self, *, icon: str, heading: str, body_lines: list[str], accent_color: int):
        super().__init__(timeout=None)
        footer_text = (
            f"All Rights Reserved to **{config.SERVER_NAME}** Team - "
            f"{datetime.now().strftime('%B %d, %Y')}"
        )
        items = [
            discord.ui.TextDisplay(f"# {icon} {heading}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay("\n".join(body_lines)),
            discord.ui.Separator(),
            discord.ui.TextDisplay(footer_text),
        ]
        container = discord.ui.Container(*items, accent_color=accent_color)
        self.add_item(container)


# ══════════════════════════════════════════════════════════════════════════
#  Staff-facing: Accept / Reject / Ask buttons
# ══════════════════════════════════════════════════════════════════════════
class ApplyReviewView(discord.ui.View):
    def __init__(self, kind: str = "staff", applicant_id: int = 0):
        super().__init__(timeout=None)
        self.kind = kind
        self.applicant_id = applicant_id
        self.btn_accept.custom_id = f"apply_accept_{kind}_{applicant_id}"
        self.btn_reject.custom_id = f"apply_reject_{kind}_{applicant_id}"
        self.btn_ask.custom_id    = f"apply_ask_{kind}_{applicant_id}"

    def _admin(self, inter: discord.Interaction) -> bool:
        # Admins / manage-roles always allowed
        if inter.user.guild_permissions.administrator or inter.user.guild_permissions.manage_roles:
            return True
        # Otherwise check the configured reviewer role (read live from storage,
        # since this view is persistent and rebuilt across restarts).
        kind, _ = self._parse_ids()
        cfg = get_kind_cfg(inter.guild_id, kind)
        reviewer_role_id = cfg.get("reviewer_role_id")
        if reviewer_role_id:
            role = inter.guild.get_role(reviewer_role_id)
            if role and role in inter.user.roles:
                return True
        return False

    def _parse_ids(self) -> tuple[str, int]:
        try:
            parts = self.btn_accept.custom_id.split("_")
            return parts[2], int(parts[3])
        except Exception:
            return self.kind, self.applicant_id

    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success, custom_id="apply_accept_0_0")
    async def btn_accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._admin(interaction):
            await interaction.response.send_message("❌ Staff only!", ephemeral=True)
            return

        kind, uid = self._parse_ids()
        member = interaction.guild.get_member(uid)
        if not member:
            await interaction.response.send_message("⚠️ Member not found!", ephemeral=True)
            return

        cfg = get_kind_cfg(interaction.guild_id, kind)
        role_id = cfg.get("role_id")
        role_given = False
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role, reason=f"Application accepted by {interaction.user}")
                    role_given = True
                except discord.Forbidden:
                    pass

        old = interaction.message.embeds[0]
        new_embed = old.copy()
        new_embed.color = config.SUCCESS_COLOR
        new_embed.title = f"{old.title} — Accepted"
        new_embed.add_field(
            name="Decision",
            value=(
                f"Accepted by: {interaction.user.mention}\n"
                f"<t:{int(datetime.now().timestamp())}:F>\n"
                f"{'Role given' if role_given else 'Could not give the role'}"
            ),
            inline=False
        )
        for c in self.children:
            c.disabled = True
        await interaction.message.edit(embed=new_embed, view=self)

        try:
            card = DecisionCardView(
                icon="✅",
                heading=f"{KIND_TITLE.get(kind, kind.title())} Application Approved",
                body_lines=[
                    f"Your {KIND_TITLE.get(kind, kind).lower()} application has been approved By {interaction.user.mention}.",
                    f"• **Server** : {interaction.guild.name}",
                ] + ([] if role_given else ["• ⚠️ The role could not be assigned automatically — contact an administrator."]),
                accent_color=config.SUCCESS_COLOR,
            )
            await member.send(view=card)
        except discord.Forbidden:
            pass

        await interaction.response.send_message(
            f"✅ Accepted {member.mention}{', role given' if role_given else ''}.",
            ephemeral=True
        )

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger, custom_id="apply_reject_0_0")
    async def btn_reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._admin(interaction):
            await interaction.response.send_message("❌ Staff only!", ephemeral=True)
            return
        kind, uid = self._parse_ids()
        await interaction.response.send_modal(RejectModal(kind=kind, applicant_id=uid, view=self))

    @discord.ui.button(label="💬 Ask", style=discord.ButtonStyle.secondary, custom_id="apply_ask_0_0")
    async def btn_ask(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._admin(interaction):
            await interaction.response.send_message("❌ Staff only!", ephemeral=True)
            return
        kind, uid = self._parse_ids()
        await interaction.response.send_modal(AskModal(applicant_id=uid))


class RejectModal(discord.ui.Modal, title="❌ Rejection Reason"):
    reason = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.paragraph,
        placeholder="Write a clear reason for the rejection...",
        max_length=500
    )

    def __init__(self, kind: str, applicant_id: int, view: ApplyReviewView):
        super().__init__()
        self.kind = kind
        self.applicant_id = applicant_id
        self.review_view = view

    async def on_submit(self, interaction: discord.Interaction):
        member = interaction.guild.get_member(self.applicant_id)
        old = interaction.message.embeds[0]
        new_embed = old.copy()
        new_embed.color = config.ERROR_COLOR
        new_embed.title = f"{old.title} — Rejected"
        new_embed.add_field(
            name="Decision",
            value=f"Rejected by {interaction.user.mention}\nReason: {self.reason.value}",
            inline=False
        )
        for c in self.review_view.children:
            c.disabled = True
        await interaction.message.edit(embed=new_embed, view=self.review_view)

        if member:
            try:
                card = DecisionCardView(
                    icon="🚫",
                    heading=f"{KIND_TITLE.get(self.kind, self.kind.title())} Application Rejected",
                    body_lines=[
                        f"Your {KIND_TITLE.get(self.kind, self.kind).lower()} application has been rejected By {interaction.user.mention}.",
                        f"• **Server** : {interaction.guild.name}",
                        f"• **Reason** : {self.reason.value}",
                    ],
                    accent_color=config.ERROR_COLOR,
                )
                await member.send(view=card)
            except Exception:
                pass
        await interaction.response.send_message("✅ Rejected and the member was notified.", ephemeral=True)


class AskModal(discord.ui.Modal, title="💬 Ask for clarification"):
    question = discord.ui.TextInput(
        label="Question to send",
        style=discord.TextStyle.paragraph,
        placeholder="What do you need clarified?",
        max_length=500
    )

    def __init__(self, applicant_id: int):
        super().__init__()
        self.applicant_id = applicant_id

    async def on_submit(self, interaction: discord.Interaction):
        member = interaction.guild.get_member(self.applicant_id)
        if not member:
            await interaction.response.send_message("⚠️ Member not found.", ephemeral=True)
            return
        try:
            card = DecisionCardView(
                icon="💬",
                heading="Application — More Info Needed",
                body_lines=[
                    "The review team needs additional information regarding your application:",
                    f"• **Question** : {self.question.value}",
                    "• Please contact an administrator to respond.",
                ],
                accent_color=config.WARNING_COLOR,
            )
            await member.send(view=card)
            await interaction.response.send_message(f"✅ Question sent to {member.mention} via DM.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("⚠️ Can't DM that member!", ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════
#  Admin-facing: /setup apply control panel
# ══════════════════════════════════════════════════════════════════════════
class SetupApplyControlView(discord.ui.View):
    def __init__(self, admin_id: int):
        super().__init__(timeout=300)
        self.admin_id = admin_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message("❌ Only the admin who ran /setup apply can use this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Set Questions", emoji="❓", style=discord.ButtonStyle.secondary)
    async def set_questions(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = _sessions.get(self.admin_id)
        if not session:
            await interaction.response.send_message("⚠️ Session expired, run `/setup apply` again.", ephemeral=True)
            return
        current = session.get("questions") or DEFAULT_QUESTIONS.get(session["kind"], [])
        await interaction.response.send_modal(QuestionsModal(self.admin_id, current))

    @discord.ui.button(label="Set Title", emoji="📝", style=discord.ButtonStyle.secondary)
    async def set_title(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = _sessions.get(self.admin_id)
        if not session:
            await interaction.response.send_message("⚠️ Session expired, run `/setup apply` again.", ephemeral=True)
            return
        await interaction.response.send_modal(TitleModal(self.admin_id, session))

    @discord.ui.button(label="Set Conditions", emoji="📋", style=discord.ButtonStyle.secondary)
    async def set_conditions(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = _sessions.get(self.admin_id)
        if not session:
            await interaction.response.send_message("⚠️ Session expired, run `/setup apply` again.", ephemeral=True)
            return
        current = session.get("conditions") or DEFAULT_CONDITIONS.get(session["kind"], [])
        await interaction.response.send_modal(ConditionsModal(self.admin_id, current))

    @discord.ui.button(label="Set Button", emoji="🎛️", style=discord.ButtonStyle.secondary)
    async def set_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = _sessions.get(self.admin_id)
        if not session:
            await interaction.response.send_message("⚠️ Session expired, run `/setup apply` again.", ephemeral=True)
            return
        await interaction.response.send_modal(ButtonModal(self.admin_id, session))

    @discord.ui.button(label="Post Panel", emoji="✅", style=discord.ButtonStyle.primary)
    async def post_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = _sessions.get(self.admin_id)
        if not session:
            await interaction.response.send_message("⚠️ Session expired, run `/setup apply` again.", ephemeral=True)
            return

        kind = session["kind"]
        apply_channel = interaction.guild.get_channel(session["apply_channel_id"])
        if not apply_channel:
            await interaction.response.send_message("❌ Apply channel not found.", ephemeral=True)
            return

        questions   = session.get("questions")   or DEFAULT_QUESTIONS.get(kind, [])
        conditions  = session.get("conditions")  or DEFAULT_CONDITIONS.get(kind, [])
        title       = session.get("title")       or f"{config.SERVER_NAME} — {KIND_LABELS.get(kind, kind.title())}"

        cfg = {
            "apply_channel_id": session["apply_channel_id"],
            "review_channel_id": session["review_channel_id"],
            "role_id": session["role_id"],
            "reviewer_role_id": session.get("reviewer_role_id"),
            "banner_url": session.get("banner_url", ""),
            "button_label": session.get("button_label", ""),
            "button_emoji": session.get("button_emoji", "↗️"),
            "button_style": session.get("button_style", "grey"),
            "footer_text": session.get("footer_text", ""),
            "description": session.get("description", ""),
            "title": title,
            "conditions": conditions,
            "questions": questions,
        }
        set_kind_cfg(interaction.guild_id, kind, cfg)
        _sessions.pop(self.admin_id, None)

        # Components V2 card — one combined message, no embed involved.
        panel_view = ApplyButtonView(kind, cfg)
        await apply_channel.send(view=panel_view)
        # Re-register as persistent so the button keeps working after a bot restart.
        interaction.client.add_view(panel_view)

        for c in self.children:
            c.disabled = True
        confirm = discord.Embed(
            title="✅ Application Panel Posted!",
            description=f"Posted in {apply_channel.mention} with {len(questions)} questions and {len(conditions)} conditions.",
            color=config.SUCCESS_COLOR
        )
        await interaction.response.edit_message(embed=confirm, view=self)


class QuestionsModal(discord.ui.Modal, title="❓ Set Application Questions"):
    q1 = discord.ui.TextInput(label="Question 1", max_length=200, required=True)
    q2 = discord.ui.TextInput(label="Question 2", max_length=200, required=True)
    q3 = discord.ui.TextInput(label="Question 3", max_length=200, required=True)
    q4 = discord.ui.TextInput(label="Question 4 (optional)", max_length=200, required=False)
    q5 = discord.ui.TextInput(label="Question 5 (optional)", max_length=200, required=False)

    def __init__(self, admin_id: int, current: list[str]):
        super().__init__()
        self.admin_id = admin_id
        fields = [self.q1, self.q2, self.q3, self.q4, self.q5]
        for i, field in enumerate(fields):
            if i < len(current):
                field.default = current[i]

    async def on_submit(self, interaction: discord.Interaction):
        questions = [q.value for q in [self.q1, self.q2, self.q3, self.q4, self.q5] if q.value]
        session = _sessions.setdefault(self.admin_id, {})
        session["questions"] = questions
        embed = discord.Embed(title="✅ Questions Saved", color=config.SUCCESS_COLOR)
        for i, q in enumerate(questions, 1):
            embed.add_field(name=f"❓ {i}", value=q, inline=False)
        embed.set_footer(text="Click Post Panel when you're ready.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ConditionsModal(discord.ui.Modal, title="📋 Set Conditions"):
    c1 = discord.ui.TextInput(label="Condition 1", max_length=200, required=True)
    c2 = discord.ui.TextInput(label="Condition 2", max_length=200, required=True)
    c3 = discord.ui.TextInput(label="Condition 3", max_length=200, required=False)
    c4 = discord.ui.TextInput(label="Condition 4 (optional)", max_length=200, required=False)
    c5 = discord.ui.TextInput(label="Condition 5 (optional)", max_length=200, required=False)

    def __init__(self, admin_id: int, current: list[str]):
        super().__init__()
        self.admin_id = admin_id
        fields = [self.c1, self.c2, self.c3, self.c4, self.c5]
        for i, field in enumerate(fields):
            if i < len(current):
                field.default = current[i]

    async def on_submit(self, interaction: discord.Interaction):
        conditions = [c.value for c in [self.c1, self.c2, self.c3, self.c4, self.c5] if c.value]
        session = _sessions.setdefault(self.admin_id, {})
        session["conditions"] = conditions
        embed = discord.Embed(title="✅ Conditions Saved", color=config.SUCCESS_COLOR)
        for i, c in enumerate(conditions, 1):
            embed.add_field(name=f"📋 {i}", value=c, inline=False)
        embed.set_footer(text="Click Post Panel when you're ready.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class TitleModal(discord.ui.Modal, title="📝 Set Title & Description"):
    title_field = discord.ui.TextInput(
        label="Panel title",
        placeholder="e.g. Ghostx Community — Staff Application",
        max_length=100,
        required=False,
    )
    description_field = discord.ui.TextInput(
        label="Description (shown under the title)",
        style=discord.TextStyle.paragraph,
        placeholder="Before applying to join our team, make sure you meet the following conditions :",
        max_length=500,
        required=False,
    )

    def __init__(self, admin_id: int, session: dict):
        super().__init__()
        self.admin_id = admin_id
        self.title_field.default = session.get("title", "")
        self.description_field.default = session.get("description", "")

    async def on_submit(self, interaction: discord.Interaction):
        session = _sessions.setdefault(self.admin_id, {})
        session["title"] = self.title_field.value.strip()
        session["description"] = self.description_field.value.strip()

        embed = discord.Embed(title="✅ Title & Description Saved", color=config.SUCCESS_COLOR)
        embed.add_field(name="Title", value=session["title"] or "(default)", inline=False)
        embed.add_field(name="Description", value=session["description"] or "(default)", inline=False)
        embed.set_footer(text="Click Post Panel when you're ready.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ButtonModal(discord.ui.Modal, title="🎛️ Customize Button & Message"):
    label_field = discord.ui.TextInput(
        label="Button label",
        placeholder="e.g. Staff Application / Apply for Whitelist",
        max_length=80,
        required=False,
    )
    emoji_field = discord.ui.TextInput(
        label="Button emoji",
        placeholder="e.g. ↗️ or a custom emoji like <:name:id>",
        max_length=80,
        required=False,
    )
    style_field = discord.ui.TextInput(
        label="Button color: grey / blue / green / red",
        placeholder="grey",
        max_length=20,
        required=False,
    )
    footer_field = discord.ui.TextInput(
        label="Message shown next to the button",
        style=discord.TextStyle.paragraph,
        placeholder="With love, Ghostx Team.",
        max_length=200,
        required=False,
    )

    def __init__(self, admin_id: int, session: dict):
        super().__init__()
        self.admin_id = admin_id
        self.label_field.default = session.get("button_label", "")
        self.emoji_field.default = session.get("button_emoji", "↗️")
        self.style_field.default = session.get("button_style", "grey")
        self.footer_field.default = session.get("footer_text", "")

    async def on_submit(self, interaction: discord.Interaction):
        session = _sessions.setdefault(self.admin_id, {})
        session["button_label"] = self.label_field.value.strip()
        session["button_emoji"] = self.emoji_field.value.strip()
        style = self.style_field.value.strip().lower() or "grey"
        if style not in BUTTON_STYLES:
            style = "grey"
        session["button_style"] = style
        session["footer_text"] = self.footer_field.value.strip()

        embed = discord.Embed(title="✅ Button & Message Saved", color=config.SUCCESS_COLOR)
        embed.add_field(name="Label", value=session["button_label"] or "(default)", inline=True)
        embed.add_field(name="Emoji", value=session["button_emoji"] or "(none)", inline=True)
        embed.add_field(name="Color", value=style, inline=True)
        embed.add_field(name="Message", value=session["footer_text"] or "(default)", inline=False)
        embed.set_footer(text="Click Post Panel when you're ready.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════
#  Cog
# ══════════════════════════════════════════════════════════════════════════
class ApplySystem(commands.Cog):
    setup_group = app_commands.Group(
        name="setup",
        description="⚙️ Bot setup commands",
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(self, bot):
        self.bot = bot

    @setup_group.command(name="apply", description="📋 Configure the whitelist or staff application system")
    @app_commands.describe(
        kind="Which application system to configure",
        apply_channel="Channel where the Apply button will be posted",
        review_channel="Channel where staff review applications",
        role="Role given automatically when an application is accepted",
        reviewer_role="Role allowed to Accept/Reject/Ask applications (optional, besides admins)",
        banner_url="Banner image URL for the panel embed (optional)",
    )
    @app_commands.choices(kind=[
        app_commands.Choice(name="📋 Staff Application", value="staff"),
        app_commands.Choice(name="🎮 Whitelist Application", value="whitelist"),
    ])
    async def setup_apply(
        self,
        interaction: discord.Interaction,
        kind: str,
        apply_channel: discord.TextChannel,
        review_channel: discord.TextChannel,
        role: discord.Role,
        reviewer_role: discord.Role = None,
        banner_url: str = None,
    ):
        existing = get_kind_cfg(interaction.guild_id, kind)
        _sessions[interaction.user.id] = {
            "kind": kind,
            "apply_channel_id": apply_channel.id,
            "review_channel_id": review_channel.id,
            "role_id": role.id,
            "reviewer_role_id": reviewer_role.id if reviewer_role else existing.get("reviewer_role_id"),
            "banner_url": banner_url or existing.get("banner_url", ""),
            "title": existing.get("title", ""),
            "conditions": existing.get("conditions", []),
            "questions": existing.get("questions", []),
        }

        reviewer_line = ""
        reviewer_id_final = _sessions[interaction.user.id]["reviewer_role_id"]
        if reviewer_id_final:
            reviewer_role_obj = interaction.guild.get_role(reviewer_id_final)
            if reviewer_role_obj:
                reviewer_line = f"🛂 Reviewer role: {reviewer_role_obj.mention}\n"

        embed = discord.Embed(
            title=f"⚙️ {KIND_LABELS.get(kind, kind.title())} Setup",
            description=(
                f"📢 Apply channel: {apply_channel.mention}\n"
                f"🔒 Review channel: {review_channel.mention}\n"
                f"🏅 Role on accept: {role.mention}\n"
                f"{reviewer_line}\n"
                "Use the buttons below to set **questions** and **conditions**, "
                "then click **Post Panel** to publish the panel."
            ),
            color=config.EMBED_COLOR
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, view=SetupApplyControlView(interaction.user.id), ephemeral=True)

    @setup_group.command(name="guide", description="📚 Full bot setup guide")
    async def setup_guide(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"⚙️ {config.BOT_NAME} — Setup Guide",
            description=f"**{config.SERVER_NAME}** | Developer: **{config.DEVELOPER}**",
            color=config.EMBED_COLOR
        )
        embed.add_field(name="👋 Welcome System",  value="`/welcome setup` — Set up the welcome system", inline=False)
        embed.add_field(name="🎫 Ticket System",   value="`/ticket setup` — Set up the ticket system", inline=False)
        embed.add_field(name="🌟 Boost System",    value="`/boost setup` — Set up the boost approval system", inline=False)
        embed.add_field(name="✅ Verify System",   value="`/verify-setup` — Set up member verification", inline=False)
        embed.add_field(name="📋 Applications",    value="`/setup apply` — Configure staff or whitelist applications", inline=False)
        embed.add_field(name="🎭 Reaction Roles",  value="`/reactionrole add` — Link emoji+role to any message", inline=False)
        embed.add_field(name="🔨 Admin Commands",  value="`/ban` `/kick` `/mute` `/warn` `/lock` `/unlock` `/clear` `/slowmode` `/role`", inline=False)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ApplySystem(bot))
