"""
نظام طلبات الستاف — Staff Apply
• العضو يضغط "تقديم طلب" ← يجيب على أسئلة مخصصة
• الطلب يذهب للروم السري → الأدمن يقبل أو يرفض
• عند القبول: تُعطى الرتبة تلقائياً + DM للعضو
"""
import discord
from discord.ext import commands
from discord import app_commands
import config
import settings
from datetime import datetime

# ══════════════════════════════════════════════════
# 📋  بناء Modal ديناميكي حسب الأسئلة المحفوظة
# ══════════════════════════════════════════════════
def build_apply_modal(questions: list[str]):
    fields = {}
    for i, q in enumerate(questions[:5]):
        fields[f"a{i}"] = discord.ui.TextInput(
            label=q[:45],
            style=discord.TextStyle.paragraph if i >= 2 else discord.TextStyle.short,
            placeholder="اكتب إجابتك هنا...",
            max_length=500,
            required=True,
        )

    async def on_submit(self, interaction: discord.Interaction):
        answers = [getattr(self, f"a{i}").value for i in range(len(questions))]
        await _send_to_review(interaction, questions, answers)

    attrs = {"__discord_ui_modal__": True, "title": "📋 طلب انضمام للستاف", "on_submit": on_submit}
    attrs.update(fields)
    ModalClass = type("StaffApplyModal", (discord.ui.Modal,), attrs)
    return ModalClass


async def _send_to_review(interaction: discord.Interaction, questions: list, answers: list):
    rev_id = settings.get("staff_review_channel_id")
    review_ch = interaction.guild.get_channel(rev_id) if rev_id else None
    if not review_ch:
        await interaction.response.send_message(
            "❌ لم يتم إعداد روم المراجعة بعد! تواصل مع الأدمن.", ephemeral=True
        )
        return

    embed = discord.Embed(
        title="Staff Application — New",
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
        name="Account age",
        value=f"<t:{int(interaction.user.created_at.timestamp())}:R>",
        inline=True
    )
    if interaction.user.joined_at:
        embed.add_field(
            name="Joined server",
            value=f"<t:{int(interaction.user.joined_at.timestamp())}:R>",
            inline=True
        )
    embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

    view = ReviewView(applicant_id=interaction.user.id)
    await review_ch.send(embed=embed, view=view)

    confirm = discord.Embed(
        title="✅ تم إرسال طلبك!",
        description=(
            "📨 وصل طلبك لفريق الإدارة وسيتم مراجعته قريباً.\n"
            "سيصلك DM عند اتخاذ القرار. 📬"
        ),
        color=config.SUCCESS_COLOR
    )
    confirm.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
    await interaction.response.send_message(embed=confirm, ephemeral=True)


# ══════════════════════════════════════════════════
# 🔘  أزرار المراجعة (للأدمن)
# ══════════════════════════════════════════════════
class ReviewView(discord.ui.View):
    def __init__(self, applicant_id: int = 0):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        # custom_id ثابت يحتوي الـ ID لكي يعمل بعد ريستارت
        self.btn_accept.custom_id = f"sapp_accept_{applicant_id}"
        self.btn_reject.custom_id = f"sapp_reject_{applicant_id}"
        self.btn_ask.custom_id    = f"sapp_ask_{applicant_id}"

    def _admin(self, inter: discord.Interaction) -> bool:
        return inter.user.guild_permissions.administrator

    def _get_id(self) -> int:
        # استخراج ID من custom_id عند الاستعادة من الريستارت
        try:
            return int(self.btn_accept.custom_id.split("_")[-1])
        except Exception:
            return self.applicant_id

    # ── ✅ قبول ──
    @discord.ui.button(label="✅ قبول", style=discord.ButtonStyle.success, custom_id="sapp_accept_0")
    async def btn_accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._admin(interaction):
            await interaction.response.send_message("❌ للأدمن فقط!", ephemeral=True)
            return

        uid = self._get_id()
        member = interaction.guild.get_member(uid)
        if not member:
            await interaction.response.send_message("⚠️ العضو غير موجود في السيرفر!", ephemeral=True)
            return

        # إعطاء الرتبة
        role_id = settings.get("staff_role_id")
        role_given = False
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role, reason=f"قُبل في الستاف بواسطة {interaction.user}")
                    role_given = True
                except discord.Forbidden:
                    pass

        # تعديل الإيمبد
        old = interaction.message.embeds[0]
        new_embed = old.copy()
        new_embed.color = config.SUCCESS_COLOR
        new_embed.title = "Staff Application — Accepted"
        new_embed.add_field(
            name="Decision",
            value=(
                f"Accepted by: {interaction.user.mention}\n"
                f"<t:{int(datetime.now().timestamp())}:F>\n"
                f"{'Role assigned' if role_given else 'Role could not be assigned'}"
            ),
            inline=False
        )
        for c in self.children:
            c.disabled = True
        await interaction.message.edit(embed=new_embed, view=self)

        # DM للعضو
        try:
            dm = discord.Embed(
                title=f"Staff Application Update — {interaction.guild.name}",
                description=(
                    f"Your application to join the staff team has been accepted.\n\n"
                    f"{'The staff role has been assigned to your account.' if role_given else 'The staff role could not be assigned automatically — please contact an administrator.'}"
                ),
                color=config.SUCCESS_COLOR,
                timestamp=datetime.now()
            )
            dm.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
            await member.send(embed=dm)
        except discord.Forbidden:
            pass

        await interaction.response.send_message(
            f"✅ تم قبول {member.mention}{'، وإعطاؤه الرتبة' if role_given else ' (تحقق من صلاحيات البوت)'}.",
            ephemeral=True
        )

    # ── ❌ رفض ──
    @discord.ui.button(label="❌ رفض", style=discord.ButtonStyle.danger, custom_id="sapp_reject_0")
    async def btn_reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._admin(interaction):
            await interaction.response.send_message("❌ للأدمن فقط!", ephemeral=True)
            return
        uid = self._get_id()
        await interaction.response.send_modal(
            RejectModal(applicant_id=uid, msg=interaction.message, view=self)
        )

    # ── 💬 طلب توضيح ──
    @discord.ui.button(label="💬 طلب توضيح", style=discord.ButtonStyle.secondary, custom_id="sapp_ask_0")
    async def btn_ask(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._admin(interaction):
            await interaction.response.send_message("❌ للأدمن فقط!", ephemeral=True)
            return
        uid = self._get_id()
        await interaction.response.send_modal(AskModal(applicant_id=uid))


class RejectModal(discord.ui.Modal, title="❌ سبب الرفض"):
    reason = discord.ui.TextInput(
        label="سبب الرفض (سيُرسل للعضو عبر DM)",
        style=discord.TextStyle.paragraph,
        placeholder="اكتب سبب الرفض...",
        max_length=500
    )

    def __init__(self, applicant_id: int, msg: discord.Message, view: ReviewView):
        super().__init__()
        self.applicant_id = applicant_id
        self.msg = msg
        self.parent_view = view

    async def on_submit(self, interaction: discord.Interaction):
        member = interaction.guild.get_member(self.applicant_id)

        old = self.msg.embeds[0]
        new_embed = old.copy()
        new_embed.color = config.ERROR_COLOR
        new_embed.title = "Staff Application — Rejected"
        new_embed.add_field(
            name="Decision",
            value=(
                f"Rejected by: {interaction.user.mention}\n"
                f"<t:{int(datetime.now().timestamp())}:F>\n"
                f"Reason: {self.reason.value}"
            ),
            inline=False
        )
        for c in self.parent_view.children:
            c.disabled = True
        await self.msg.edit(embed=new_embed, view=self.parent_view)

        if member:
            try:
                dm = discord.Embed(
                    title=f"Staff Application Update — {interaction.guild.name}",
                    description=(
                        f"Your application to join the staff team has been rejected.\n\n"
                        f"**Reason:**\n{self.reason.value}\n\n"
                        f"You are welcome to apply again in the future."
                    ),
                    color=config.ERROR_COLOR,
                    timestamp=datetime.now()
                )
                dm.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
                await member.send(embed=dm)
            except discord.Forbidden:
                pass

        await interaction.response.send_message(
            f"✅ تم الرفض{' وإشعار العضو.' if member else ' (العضو غير موجود).'}",
            ephemeral=True
        )


class AskModal(discord.ui.Modal, title="💬 طلب توضيح إضافي"):
    question = discord.ui.TextInput(
        label="السؤال أو التوضيح المطلوب",
        style=discord.TextStyle.paragraph,
        placeholder="اكتب ما تريد توضيحه من المتقدم...",
        max_length=500
    )

    def __init__(self, applicant_id: int):
        super().__init__()
        self.applicant_id = applicant_id

    async def on_submit(self, interaction: discord.Interaction):
        member = interaction.guild.get_member(self.applicant_id)
        if not member:
            await interaction.response.send_message("⚠️ العضو غير موجود!", ephemeral=True)
            return
        try:
            dm = discord.Embed(
                title=f"Staff Application Update — {interaction.guild.name}",
                description=(
                    f"The staff team needs additional clarification regarding your application:\n\n"
                    f"**Question:**\n{self.question.value}\n\n"
                    f"Please contact an administrator to respond."
                ),
                color=config.WARNING_COLOR,
                timestamp=datetime.now()
            )
            dm.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
            await member.send(embed=dm)
            await interaction.response.send_message(
                f"✅ تم إرسال السؤال لـ {member.mention} عبر DM.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message("⚠️ DM العضو مغلق!", ephemeral=True)


# ══════════════════════════════════════════════════
# 🟢  زر "تقديم طلب" — Persistent
# ══════════════════════════════════════════════════
class StaffApplyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📋 تقديم طلب ستاف",
        style=discord.ButtonStyle.secondary,
        custom_id="staff_apply_btn",
        emoji="📋"
    )
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        questions = settings.get("staff_questions") or [
            "ما اسمك وعمرك؟",
            "كم ساعة يمكنك تخصيصها للسيرفر يومياً؟",
            "هل لديك خبرة سابقة في الإدارة؟",
            "لماذا تريد الانضمام لفريق الستاف؟",
            "كيف ستتعامل مع عضو يخالف القوانين؟",
        ]
        ModalClass = build_apply_modal(questions)
        await interaction.response.send_modal(ModalClass())


# ══════════════════════════════════════════════════
# 🤖  Cog الرئيسي
# ══════════════════════════════════════════════════
class StaffApplication(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="staff-setup", description="⚙️ إعداد نظام طلبات الستاف")
    @app_commands.describe(
        apply_channel="الروم اللي يظهر فيه زر التقديم",
        review_channel="الروم السري للأدمن لمراجعة الطلبات",
        staff_role="الرتبة اللي تُعطى عند القبول",
        banner_url="رابط صورة بانر للإيمبد (اختياري)"
    )
    @app_commands.default_permissions(administrator=True)
    async def staff_setup(
        self,
        interaction: discord.Interaction,
        apply_channel: discord.TextChannel,
        review_channel: discord.TextChannel,
        staff_role: discord.Role,
        banner_url: str = None
    ):
        settings.set_many({
            "staff_app_channel_id":    apply_channel.id,
            "staff_review_channel_id": review_channel.id,
            "staff_role_id":           staff_role.id,
        })

        questions = settings.get("staff_questions") or []

        embed = discord.Embed(
            title=f"📋 نظام طلبات الستاف — {config.SERVER_NAME}",
            description=(
                "**هل تريد الانضمام لفريق الستاف؟** 🎖️\n\n"
                "📝 اضغط الزر أدناه وأجب على الأسئلة\n"
                "⏰ ستتم المراجعة من قِبل الإدارة\n"
                "📨 ستصلك رسالة خاصة بالنتيجة\n\n"
                f"**📋 عدد الأسئلة:** {len(questions)}"
            ),
            color=config.EMBED_COLOR
        )
        if banner_url and banner_url.startswith("http"):
            embed.set_image(url=banner_url)
        embed.add_field(name="👥 المراجعة", value=f"الأدمن في {review_channel.mention}", inline=True)
        embed.add_field(name="🏅 الرتبة عند القبول", value=staff_role.mention, inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

        view = StaffApplyView()
        await apply_channel.send(embed=embed, view=view)

        success = discord.Embed(
            title="✅ تم إعداد نظام الستاف",
            description=(
                f"• روم التقديم: {apply_channel.mention}\n"
                f"• روم المراجعة: {review_channel.mention}\n"
                f"• الرتبة: {staff_role.mention}\n"
                f"• عدد الأسئلة: {len(questions)}"
            ),
            color=config.SUCCESS_COLOR
        )
        success.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=success, ephemeral=True)

    @app_commands.command(name="staff-questions", description="❓ تخصيص أسئلة طلب الستاف (3 إلى 5 أسئلة)")
    @app_commands.describe(
        q1="السؤال الأول",
        q2="السؤال الثاني",
        q3="السؤال الثالث",
        q4="السؤال الرابع — اختياري",
        q5="السؤال الخامس — اختياري"
    )
    @app_commands.default_permissions(administrator=True)
    async def staff_questions(
        self,
        interaction: discord.Interaction,
        q1: str, q2: str, q3: str,
        q4: str = None, q5: str = None
    ):
        questions = [q for q in [q1, q2, q3, q4, q5] if q]
        settings.set("staff_questions", questions)

        embed = discord.Embed(title="✅ تم تحديث أسئلة الستاف", color=config.SUCCESS_COLOR)
        for i, q in enumerate(questions, 1):
            embed.add_field(name=f"❓ السؤال {i}", value=q, inline=False)
        embed.set_footer(text=f"أعد إرسال /staff-setup لتطبيق الأسئلة الجديدة | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="staff-channel", description="🔄 تغيير رومات نظام الستاف")
    @app_commands.describe(
        apply_channel="روم زر التقديم — اختياري",
        review_channel="روم مراجعة الأدمن — اختياري",
        staff_role="رتبة الستاف — اختياري"
    )
    @app_commands.default_permissions(administrator=True)
    async def staff_channel(
        self,
        interaction: discord.Interaction,
        apply_channel: discord.TextChannel = None,
        review_channel: discord.TextChannel = None,
        staff_role: discord.Role = None
    ):
        updates = {}
        if apply_channel:
            updates["staff_app_channel_id"] = apply_channel.id
        if review_channel:
            updates["staff_review_channel_id"] = review_channel.id
        if staff_role:
            updates["staff_role_id"] = staff_role.id

        if not updates:
            await interaction.response.send_message("❌ يجب تحديد عنصر واحد على الأقل!", ephemeral=True)
            return

        settings.set_many(updates)

        embed = discord.Embed(title="✅ تم تحديث إعدادات الستاف", color=config.SUCCESS_COLOR)
        if apply_channel:
            embed.add_field(name="📋 روم التقديم", value=apply_channel.mention, inline=True)
        if review_channel:
            embed.add_field(name="🔒 روم المراجعة", value=review_channel.mention, inline=True)
        if staff_role:
            embed.add_field(name="🏅 الرتبة", value=staff_role.mention, inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="staff-info", description="📊 عرض إعدادات نظام الستاف الحالية")
    @app_commands.default_permissions(administrator=True)
    async def staff_info(self, interaction: discord.Interaction):
        s = settings.all_settings()
        app_ch  = interaction.guild.get_channel(s.get("staff_app_channel_id") or 0)
        rev_ch  = interaction.guild.get_channel(s.get("staff_review_channel_id") or 0)
        role    = interaction.guild.get_role(s.get("staff_role_id") or 0)
        questions = s.get("staff_questions") or []

        embed = discord.Embed(title="📊 إعدادات نظام الستاف", color=config.EMBED_COLOR)
        embed.add_field(name="📋 روم التقديم",  value=app_ch.mention if app_ch else "❌ غير محدد", inline=True)
        embed.add_field(name="🔒 روم المراجعة", value=rev_ch.mention if rev_ch else "❌ غير محدد", inline=True)
        embed.add_field(name="🏅 الرتبة",       value=role.mention if role else "❌ غير محدد", inline=True)
        embed.add_field(name="📋 الأسئلة الحالية", value=f"{len(questions)} سؤال", inline=True)
        for i, q in enumerate(questions, 1):
            embed.add_field(name=f"❓ {i}", value=q, inline=False)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(StaffApplication(bot))
 