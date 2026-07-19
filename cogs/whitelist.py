import discord
from discord.ext import commands
from discord import app_commands
import config
from datetime import datetime
import asyncio

pending_applications = {}

# ============================================================
#  مودال الطلب
# ============================================================
class WhitelistModal(discord.ui.Modal, title="📋 طلب الوايتليست — RolePlay"):
    real_age = discord.ui.TextInput(
        label="🎂 كم عمرك في الواقع؟",
        placeholder="مثال: 20",
        max_length=3, min_length=1
    )
    real_name = discord.ui.TextInput(
        label="👤 اسمك الحقيقي",
        placeholder="مثال: أحمد محمد",
        max_length=50
    )
    game_name = discord.ui.TextInput(
        label="🎮 اسمك في اللعبة (Game Name)",
        placeholder="مثال: Ahmed_Al_Farsi",
        max_length=50
    )
    rp_rules = discord.ui.TextInput(
        label="📜 ما هي أهم قوانين الـ RolePlay؟",
        style=discord.TextStyle.paragraph,
        placeholder="NLR - RDM - PowerGaming ... اكتب ما تعرفه",
        max_length=800, min_length=30
    )
    story = discord.ui.TextInput(
        label="📖 قصة شخصيتك في اللعبة",
        style=discord.TextStyle.paragraph,
        placeholder="من أنت؟ ماذا تعمل؟ لماذا أتيت؟ (50 حرف على الأقل)",
        max_length=1000, min_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        pending_applications[interaction.user.id] = {
            "real_age":  self.real_age.value,
            "real_name": self.real_name.value,
            "game_name": self.game_name.value,
            "rp_rules":  self.rp_rules.value,
            "story":     self.story.value,
            "submitted_at": datetime.now()
        }
        embed = discord.Embed(
            title="⚖️ اختر نوع شخصيتك",
            description=(
                "🟢 **Legal** — شخصية قانونية (مواطن، طبيب، ميكانيكي، شرطي...)\n"
                "🔴 **Illegal** — شخصية غير قانونية (مافيا، مجرم، مهرب...)\n\n"
                "⚠️ اختيارك يحدد مسار شخصيتك في اللعبة"
            ),
            color=config.EMBED_COLOR
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, view=LegalChoiceView(), ephemeral=True)


# ============================================================
#  أزرار Legal / Illegal
# ============================================================
class LegalChoiceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="🟢 Legal",   style=discord.ButtonStyle.success, custom_id="wl_choice_legal")
    async def legal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._submit(interaction, "Legal 🟢")

    @discord.ui.button(label="🔴 Illegal", style=discord.ButtonStyle.danger,  custom_id="wl_choice_illegal")
    async def illegal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._submit(interaction, "Illegal 🔴")

    async def _submit(self, interaction: discord.Interaction, choice: str):
        data = pending_applications.get(interaction.user.id)
        if not data:
            await interaction.response.send_message(
                "❌ انتهت صلاحية الطلب! اضغط التقديم من جديد.", ephemeral=True
            )
            return

        # بناء إمباد المراجعة
        app_embed = discord.Embed(title="📋 طلب وايتليست جديد", color=0xFFD700, timestamp=datetime.now())
        app_embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        app_embed.set_thumbnail(url=interaction.user.display_avatar.url)
        app_embed.add_field(name="👤 المتقدم",       value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=True)
        app_embed.add_field(name="🎂 العمر",          value=data["real_age"],  inline=True)
        app_embed.add_field(name="⚖️ النوع",          value=choice,            inline=True)
        app_embed.add_field(name="🪪 الاسم الحقيقي", value=data["real_name"], inline=True)
        app_embed.add_field(name="🎮 اسم اللعبة",    value=data["game_name"], inline=True)
        app_embed.add_field(name="📅 التوقيت",        value=f"<t:{int(datetime.now().timestamp())}:F>", inline=True)
        app_embed.add_field(name="📜 معرفة قوانين RP", value=f"```{data['rp_rules'][:900]}```", inline=False)
        app_embed.add_field(name="📖 القصة",          value=f"```{data['story'][:900]}```", inline=False)
        app_embed.set_footer(text=f"ID المتقدم: {interaction.user.id} | {config.BOT_NAME}")

        review_channel_id = getattr(config, 'WHITELIST_REVIEW_CHANNEL', None)
        review_channel = interaction.client.get_channel(review_channel_id) if review_channel_id else None

        if review_channel:
            # نخزن ID في content باش نقدرو نقراه من ReviewView
            await review_channel.send(
                content=f"APPLICANT_ID:{interaction.user.id}",
                embed=app_embed,
                view=ReviewView()
            )
        else:
            await interaction.response.send_message(
                "⚠️ روم المراجعة غير محدد! تواصل مع الأدمن.", ephemeral=True
            )
            return

        confirm = discord.Embed(
            title="✅ تم إرسال طلبك!",
            description=(
                f"🎮 الاسم: **{data['game_name']}**\n"
                f"⚖️ النوع: **{choice}**\n\n"
                "⏰ انتظر رد الإدارة — ستصلك رسالة خاصة عند القرار"
            ),
            color=config.SUCCESS_COLOR
        )
        confirm.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=confirm, ephemeral=True)

        pending_applications.pop(interaction.user.id, None)
        self.stop()


# ============================================================
#  أزرار المراجعة — persistent (بدون arguments)
# ============================================================
class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def _get_applicant_id(self, message: discord.Message) -> int | None:
        """يقرأ ID المتقدم من content الرسالة"""
        try:
            if message.content.startswith("APPLICANT_ID:"):
                return int(message.content.split(":")[1])
        except:
            pass
        # fallback: نقرأ من footer الإمباد
        try:
            footer = message.embeds[0].footer.text
            for part in footer.split("|"):
                part = part.strip()
                if part.startswith("ID المتقدم:"):
                    return int(part.split(":")[1].strip())
        except:
            pass
        return None

    @discord.ui.button(label="✅ قبول",           style=discord.ButtonStyle.success,   custom_id="wl_review_approve", emoji="✅")
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ ليس لديك صلاحية!", ephemeral=True)
            return
        applicant_id = self._get_applicant_id(interaction.message)
        await self._handle(interaction, approved=True, applicant_id=applicant_id)

    @discord.ui.button(label="❌ رفض",            style=discord.ButtonStyle.danger,     custom_id="wl_review_reject",  emoji="❌")
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ ليس لديك صلاحية!", ephemeral=True)
            return
        applicant_id = self._get_applicant_id(interaction.message)
        await interaction.response.send_modal(RejectModal(applicant_id, interaction.message))

    @discord.ui.button(label="⚠️ مراجعة إضافية", style=discord.ButtonStyle.secondary,  custom_id="wl_review_pending",  emoji="⚠️")
    async def pending_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ ليس لديك صلاحية!", ephemeral=True)
            return
        applicant_id = self._get_applicant_id(interaction.message)
        member = interaction.guild.get_member(applicant_id) if applicant_id else None
        if member:
            try:
                dm = discord.Embed(
                    title="⚠️ طلبك قيد المراجعة",
                    description=f"طلبك في **{config.SERVER_NAME}** يحتاج مراجعة إضافية. سيتم إشعارك قريباً.",
                    color=config.WARNING_COLOR
                )
                await member.send(embed=dm)
            except:
                pass
        embed = interaction.message.embeds[0]
        embed.color = config.WARNING_COLOR
        embed.add_field(name="⚠️ الحالة", value=f"قيد المراجعة — {interaction.user.mention}", inline=False)
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("✅ تم وضع الطلب قيد المراجعة.", ephemeral=True)

    async def _handle(self, interaction: discord.Interaction, approved: bool,
                      applicant_id: int | None, reason: str = None):
        member = interaction.guild.get_member(applicant_id) if applicant_id else None

        embed = interaction.message.embeds[0]

        if approved:
            wl_role_id = getattr(config, 'WHITELIST_ROLE_ID', None)
            if wl_role_id and member:
                role = interaction.guild.get_role(wl_role_id)
                if role:
                    try:
                        await member.add_roles(role)
                    except Exception as e:
                        await interaction.response.send_message(f"⚠️ ما قدرتش نعطي الرتبة: {e}", ephemeral=True)
                        return

            embed.color = 0x00FF00
            embed.add_field(name="✅ القرار", value=f"**مقبول** — {interaction.user.mention}", inline=False)
            await interaction.message.edit(content="", embed=embed, view=None)

            if member:
                try:
                    dm = discord.Embed(
                        title="🎉 تم قبول طلب الوايتليست!",
                        description=(
                            f"**تهانينا {member.mention}!**\n\n"
                            f"✅ تم قبولك في **{config.SERVER_NAME}**\n"
                            "🎮 يمكنك الآن البدء باللعب!\n"
                            "📖 التزم بقوانين السيرفر دائماً"
                        ),
                        color=0x00FF00
                    )
                    dm.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
                    await member.send(embed=dm)
                except:
                    pass
            await interaction.response.send_message("✅ تم القبول وإعطاء الرتبة!", ephemeral=True)

        else:
            embed.color = 0xFF0000
            embed.add_field(
                name="❌ القرار",
                value=f"**مرفوض** — {interaction.user.mention}\n📝 السبب: {reason or 'لم يذكر'}",
                inline=False
            )
            await interaction.message.edit(content="", embed=embed, view=None)

            if member:
                try:
                    dm = discord.Embed(
                        title="❌ تم رفض طلبك",
                        description=(
                            f"**عذراً {member.mention}**\n\n"
                            f"❌ تم رفض طلبك في **{config.SERVER_NAME}**\n"
                            f"📝 السبب: {reason or 'لم يذكر'}\n"
                            "🔄 يمكنك إعادة التقديم لاحقاً"
                        ),
                        color=0xFF0000
                    )
                    dm.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
                    await member.send(embed=dm)
                except:
                    pass
            await interaction.response.send_message("✅ تم الرفض وإشعار العضو.", ephemeral=True)


class RejectModal(discord.ui.Modal, title="❌ سبب الرفض"):
    reason = discord.ui.TextInput(
        label="سبب الرفض",
        style=discord.TextStyle.paragraph,
        placeholder="اكتب سبب الرفض بوضوح...",
        max_length=500
    )

    def __init__(self, applicant_id: int | None, original_message: discord.Message):
        super().__init__()
        self.applicant_id    = applicant_id
        self.original_message = original_message

    async def on_submit(self, interaction: discord.Interaction):
        view = ReviewView()
        await view._handle(interaction, approved=False,
                           applicant_id=self.applicant_id,
                           reason=self.reason.value)


# ============================================================
#  زر التقديم في روم الوايتليست — persistent
# ============================================================
class WhitelistApplyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📋 تقديم طلب الوايتليست",
        style=discord.ButtonStyle.primary,
        custom_id="wl_apply_main",
        emoji="📋"
    )
    async def apply_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        wl_role_id = getattr(config, 'WHITELIST_ROLE_ID', None)
        if wl_role_id:
            role = interaction.guild.get_role(wl_role_id)
            if role and role in interaction.user.roles:
                await interaction.response.send_message(
                    "⚠️ أنت حاصل على الوايتليست بالفعل!", ephemeral=True
                )
                return
        await interaction.response.send_modal(WhitelistModal())


# ============================================================
#  الكوج الرئيسي
# ============================================================
class Whitelist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="whitelist-setup", description="📋 إعداد نظام الوايتليست RP")
    @app_commands.describe(
        channel="روم التقديم",
        review_channel="روم مراجعة الطلبات (للأدمن)",
        whitelist_role="الرتبة التي تُعطى عند القبول",
        banner_url="رابط بانر (اختياري)"
    )
    @app_commands.default_permissions(administrator=True)
    async def whitelist_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        review_channel: discord.TextChannel,
        whitelist_role: discord.Role,
        banner_url: str = None
    ):
        config.WHITELIST_REVIEW_CHANNEL = review_channel.id
        config.WHITELIST_ROLE_ID        = whitelist_role.id

        embed = discord.Embed(
            title=f"🎮 الوايتليست — {config.SERVER_NAME}",
            description=(
                "## 📋 التقديم على الوايتليست\n\n"
                "للانضمام إلى عالم الـ **RolePlay** اضغط الزر أدناه\n\n"
                "### 📌 سيُطلب منك:\n"
                "🎂 عمرك الحقيقي\n"
                "👤 اسمك الحقيقي\n"
                "🎮 اسمك في اللعبة\n"
                "📜 ما تعرفه عن قوانين RP\n"
                "📖 قصة شخصيتك بالتفصيل\n"
                "⚖️ نوع الشخصية (Legal / Illegal)\n\n"
                "⚠️ *إجابات قصيرة أو غير جدية = رفض تلقائي*"
            ),
            color=config.EMBED_COLOR
        )
        if banner_url and banner_url.startswith("http"):
            embed.set_image(url=banner_url)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

        await channel.send(embed=embed, view=WhitelistApplyView())

        success = discord.Embed(
            title="✅ تم إعداد نظام الوايتليست",
            description=(
                f"• روم التقديم: {channel.mention}\n"
                f"• روم المراجعة: {review_channel.mention}\n"
                f"• رتبة القبول: {whitelist_role.mention}\n"
                f"• البانر: {'✅' if banner_url else '❌ لا يوجد'}"
            ),
            color=config.SUCCESS_COLOR
        )
        success.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=success, ephemeral=True)

    @app_commands.command(name="whitelist-accept", description="✅ قبول عضو يدوياً")
    @app_commands.describe(member="العضو")
    @app_commands.default_permissions(administrator=True)
    async def whitelist_accept(self, interaction: discord.Interaction, member: discord.Member):
        wl_role_id = getattr(config, 'WHITELIST_ROLE_ID', None)
        if not wl_role_id:
            await interaction.response.send_message("❌ لم يتم إعداد الوايتليست!", ephemeral=True)
            return
        role = interaction.guild.get_role(wl_role_id)
        if not role:
            await interaction.response.send_message("❌ الرتبة غير موجودة!", ephemeral=True)
            return
        await member.add_roles(role)
        try:
            await member.send(embed=discord.Embed(
                title="🎉 تم قبولك في الوايتليست!",
                description=f"تم قبولك يدوياً في **{config.SERVER_NAME}**!",
                color=0x00FF00
            ))
        except:
            pass
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ تم القبول",
                description=f"{member.mention} حصل على {role.mention}",
                color=config.SUCCESS_COLOR
            ),
            ephemeral=True
        )

    @app_commands.command(name="whitelist-remove", description="🗑️ سحب وايتليست من عضو")
    @app_commands.describe(member="العضو")
    @app_commands.default_permissions(administrator=True)
    async def whitelist_remove(self, interaction: discord.Interaction, member: discord.Member):
        wl_role_id = getattr(config, 'WHITELIST_ROLE_ID', None)
        if not wl_role_id:
            await interaction.response.send_message("❌ لم يتم إعداد الوايتليست!", ephemeral=True)
            return
        role = interaction.guild.get_role(wl_role_id)
        if role and role in member.roles:
            await member.remove_roles(role)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🗑️ تم سحب الوايتليست",
                description=f"تم سحب الوايتليست من {member.mention}",
                color=config.WARNING_COLOR
            ),
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Whitelist(bot))
