"""
Resources System — Ghostx Community
────────────────────────────────────
نظام لتنظيم ونشر الموارد (سكريبتات SA-MP، بوتات ديسكورد، بلوجينز،
gamemodes...) مع مراجعة من الستاف قبل ما تتنشر، ومع تحسين تلقائي
للوصف بالـ AI.

3 رومات:
  • Info Channel   — شرح كيفية استخدام النظام (ثابت، كيتبعت مرة وحدة).
  • Panel Channel  — بانيل بزر "📦 قدّم ريسورس" (بلا ما يحتاج العضو /resource submit).
  • Review Channel — هنا كيتبعت كل طلب للستاف (قبول/رفض).

كل تصنيف (SA-MP Script / Discord Bot / ...) عندو شانل نشر خاص بيه،
كيتحدد بـ /resource setpublish — كيفما طلب: "panel samp gamemode" ينشر
فـ روم مخصصة للـ gamemodes، وهكذا لكل تصنيف.

/resource submit    — عضو كايقترح ريسورس جديد (مودال + تصنيف) — أو من البانيل
/resource list       — عرض الموارد المنشورة (بفلتر تصنيف اختياري)
/resource search     — بحث بكلمة مفتاحية فـ الاسم/الوصف
/resource setup      — (أدمن) حدد الـ 3 رومات: مراجعة / شرح / بانيل
/resource setpublish — (أدمن) حدد شانل النشر ديال تصنيف معين

التخزين: MongoDB عبر db.py — collection "resources" (كل ريسورس)
و collection "resource_settings" (الرومات + شانلات النشر، document واحد).
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import db
import os
import uuid
from datetime import datetime

CATEGORIES = ["SA-MP Script", "Discord Bot", "Plugin / Filterscript", "Gamemode", "Other"]

CATEGORY_COLORS = {
    "SA-MP Script": 0x57F287,
    "Discord Bot": 0x5865F2,
    "Plugin / Filterscript": 0xFEE75C,
    "Gamemode": 0xEB459E,
    "Other": 0x99AAB5,
}

GROQ_MODEL    = "llama-3.3-70b-versatile"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _settings() -> dict:
    return db.load_doc("resource_settings")


def _save_settings(data: dict) -> None:
    db.save_doc("resource_settings", data)


def _category_color(category: str) -> int:
    return CATEGORY_COLORS.get(category, config.EMBED_COLOR)


# ============================================================
#  AI — تحسين الوصف قبل ما يتبعت للمراجعة/النشر
# ============================================================
async def _ai_enhance_description(name: str, category: str, raw_description: str) -> str:
    """
    كيستخدم نفس نظام /ai (Groq) باش يعاود يكتب الوصف بشكل منظم وكيزيد
    معلومات منطقية (فايدة، استخدام...) بلا ما يخترع تفاصيل تقنية دقيقة
    (فيرجن، أرقام...) ماشي موجودة فـ النص الأصلي.
    إذا GROQ_API_KEY ماكاينة أو صرا خطأ، كيرجع الوصف الأصلي بلا تعديل.
    """
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return raw_description

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
        prompt = (
            f"اسم الريسورس: {name}\n"
            f"التصنيف: {category}\n"
            f"الوصف الأصلي (كتبو صاحب الريسورس):\n{raw_description}\n\n"
            "أعد كتابة هذا الوصف بشكل منظم وواضح (جمل قصيرة أو نقط)، وزيد توضيح "
            "منطقي لاستخدام هذا النوع من الموارد والفايدة منه حسب التصنيف، بلا ما "
            "تخترع أي معلومة تقنية دقيقة غير موجودة فـ النص الأصلي (فيرجن، رابط، "
            "رقم...). خاص الجواب يكون غير الوصف المحسّن، بلا مقدمة، بلا تعليق، "
            "بحد أقصى 500 حرف."
        )
        response = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "أنت مساعد كايحسن وصف الموارد (سكريبتات SA-MP، بوتات ديسكورد، "
                        "بلوجينز، gamemodes) قبل نشرها فـ سيرفر ديسكورد. جاوب غير "
                        "بالوصف المحسّن مباشرة."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=400,
            temperature=0.6,
        )
        enhanced = (response.choices[0].message.content or "").strip()
        return enhanced[:1000] if enhanced else raw_description
    except Exception:
        return raw_description


# ============================================================
#  مودال تقديم ريسورس
# ============================================================
class ResourceModal(discord.ui.Modal, title="📦 اقترح ريسورس جديد"):
    name = discord.ui.TextInput(label="📛 اسم الريسورس", max_length=80)
    link = discord.ui.TextInput(label="🔗 رابط الدونلود", max_length=300)
    version = discord.ui.TextInput(label="🏷️ فيرجن (اختياري)", max_length=30, required=False)
    description = discord.ui.TextInput(
        label="📝 وصف مختصر (شنو كايدير، شنو خاصو...)",
        style=discord.TextStyle.paragraph,
        max_length=600,
        min_length=20,
    )

    def __init__(self, category: str):
        super().__init__()
        self.category = category

    async def on_submit(self, interaction: discord.Interaction):
        settings = _settings()
        review_channel_id = settings.get("review_channel_id")
        if not review_channel_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="❌ نظام الموارد ماشي مفعّل بعد. قول لأدمن يدير `/resource setup` أولاً.",
                    color=config.ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        # 🤖 تحسين الوصف بالـ AI (يزيد تفاصيل ومعلومات مفيدة قبل النشر)
        enhanced_description = await _ai_enhance_description(
            self.name.value, self.category, self.description.value
        )

        resource_id = uuid.uuid4().hex[:10]
        resources = db.load("resources")
        resources[resource_id] = {
            "name": self.name.value,
            "category": self.category,
            "link": self.link.value,
            "version": self.version.value or "—",
            "description": self.description.value,
            "enhanced_description": enhanced_description,
            "author_id": interaction.user.id,
            "author_name": str(interaction.user),
            "status": "pending",
            "submitted_at": datetime.now().isoformat(),
        }
        db.save("resources", resources)

        review_channel = interaction.guild.get_channel(int(review_channel_id))
        if review_channel:
            embed = discord.Embed(
                title=f"📦 طلب ريسورس جديد — {self.name.value}",
                description=enhanced_description,
                color=_category_color(self.category),
                timestamp=datetime.now(),
            )
            embed.add_field(name="التصنيف", value=self.category, inline=True)
            embed.add_field(name="الفيرجن", value=self.version.value or "—", inline=True)
            embed.add_field(name="الرابط", value=self.link.value, inline=False)
            if enhanced_description != self.description.value:
                embed.add_field(name="📝 الوصف الأصلي", value=self.description.value[:1000], inline=False)
                embed.set_footer(text=f"ID: {resource_id} | ✨ الوصف محسّن بالـ AI | {config.BOT_NAME}")
            else:
                embed.set_footer(text=f"ID: {resource_id} | {config.BOT_NAME}")
            embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)

            await review_channel.send(embed=embed, view=ResourceReviewView())

        await interaction.followup.send(
            embed=discord.Embed(
                description="✅ تبعت طلبك للمراجعة! غادي توصل نتيجة فـ الخاص قريباً.",
                color=config.SUCCESS_COLOR,
            ),
            ephemeral=True,
        )


# ============================================================
#  سيليكت التصنيف (قبل المودال، خاص السيليكت ميني يكون فـ فيو)
# ============================================================
class CategorySelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=c) for c in CATEGORIES]
        super().__init__(placeholder="اختار تصنيف الريسورس...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ResourceModal(self.values[0]))


class CategorySelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(CategorySelect())


# ============================================================
#  البانيل — زر ثابت فـ Panel Channel، بلا ما يحتاج /resource submit
# ============================================================
class ResourceSubmitPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="قدّم ريسورس",
        emoji="📦",
        style=discord.ButtonStyle.success,
        custom_id="res_panel_submit",
    )
    async def submit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = _settings()
        if not settings.get("review_channel_id"):
            await interaction.response.send_message(
                "❌ نظام الموارد ماشي مفعّل بعد.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "اختار تصنيف الريسورس لي بغيتي تقترحو 👇",
            view=CategorySelectView(),
            ephemeral=True,
        )


# ============================================================
#  فيو المراجعة — persistent (Approve / Reject)
# ============================================================
class ResourceReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def _get_resource_id(self, message: discord.Message) -> str | None:
        try:
            footer = message.embeds[0].footer.text
            for part in footer.split("|"):
                part = part.strip()
                if part.startswith("ID:"):
                    return part.split(":", 1)[1].strip()
        except Exception:
            pass
        return None

    @discord.ui.button(label="✅ قبول", style=discord.ButtonStyle.success, custom_id="res_review_approve")
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ ليس لديك صلاحية!", ephemeral=True)
            return
        await self._resolve(interaction, approved=True)

    @discord.ui.button(label="❌ رفض", style=discord.ButtonStyle.danger, custom_id="res_review_reject")
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ ليس لديك صلاحية!", ephemeral=True)
            return
        await self._resolve(interaction, approved=False)

    async def _resolve(self, interaction: discord.Interaction, approved: bool):
        resource_id = self._get_resource_id(interaction.message)
        resources = db.load("resources")
        res = resources.get(resource_id) if resource_id else None

        if not res:
            await interaction.response.send_message(
                "❌ هاد الطلب ماكاينش (تحيد أو تقبل/رفض من قبل).", ephemeral=True
            )
            return

        if res["status"] != "pending":
            await interaction.response.send_message(
                f"⚠️ هاد الطلب تمت معالجته من قبل (الحالة: `{res['status']}`).", ephemeral=True
            )
            return

        author = interaction.guild.get_member(res["author_id"])
        published_description = res.get("enhanced_description") or res["description"]

        if approved:
            res["status"] = "approved"
            resources[resource_id] = res
            db.save("resources", resources)

            settings = _settings()
            publish_channels = settings.get("publish_channels", {})
            publish_channel_id = publish_channels.get(res["category"]) or settings.get("publish_channel_id")
            publish_channel = interaction.guild.get_channel(int(publish_channel_id)) if publish_channel_id else None

            if publish_channel:
                pub_embed = discord.Embed(
                    title=f"📦 {res['name']}",
                    description=published_description,
                    color=_category_color(res["category"]),
                    timestamp=datetime.now(),
                )
                pub_embed.add_field(name="التصنيف", value=res["category"], inline=True)
                pub_embed.add_field(name="الفيرجن", value=res["version"], inline=True)
                pub_embed.set_footer(text=f"من: {res['author_name']} | ✅ Verified by Staff")
                pub_view = discord.ui.View()
                pub_view.add_item(
                    discord.ui.Button(label="⬇️ دونلود", url=res["link"], style=discord.ButtonStyle.link)
                )
                await publish_channel.send(embed=pub_embed, view=pub_view)
                publish_note = f"تنشر فـ {publish_channel.mention}"
            else:
                publish_note = "⚠️ تقبل ولكن ماكاين شانل نشر محدد لهاد التصنيف — استخدم `/resource setpublish`."

            if author:
                try:
                    await author.send(embed=discord.Embed(
                        description=f"✅ تقبل الريسورس ديالك **{res['name']}** وتنشر فـ {config.SERVER_NAME}!",
                        color=config.SUCCESS_COLOR,
                    ))
                except discord.Forbidden:
                    pass

            status_text = f"✅ **{res['name']}** تقبل من طرف {interaction.user.mention} — {publish_note}"
            new_color = config.SUCCESS_COLOR
        else:
            res["status"] = "rejected"
            resources[resource_id] = res
            db.save("resources", resources)

            if author:
                try:
                    await author.send(embed=discord.Embed(
                        description=f"❌ الريسورس ديالك **{res['name']}** تم رفضو من طرف الستاف.",
                        color=config.ERROR_COLOR,
                    ))
                except discord.Forbidden:
                    pass

            status_text = f"❌ **{res['name']}** تم رفضو من طرف {interaction.user.mention}"
            new_color = config.ERROR_COLOR

        embed = interaction.message.embeds[0]
        embed.color = new_color
        embed.add_field(name="الحالة", value=status_text, inline=False)

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)


# ============================================================
#  الكوج
# ============================================================
class Resources(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    resource_group = app_commands.Group(name="resource", description="📦 نظام الموارد")

    @resource_group.command(name="submit", description="📦 اقترح ريسورس جديد (سكريبت، بوت، بلوجين...)")
    async def submit(self, interaction: discord.Interaction):
        settings = _settings()
        if not settings.get("review_channel_id"):
            await interaction.response.send_message(
                "❌ نظام الموارد ماشي مفعّل بعد. قول لأدمن يدير `/resource setup` أولاً.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "اختار تصنيف الريسورس لي بغيتي تقترحو 👇",
            view=CategorySelectView(),
            ephemeral=True,
        )

    @resource_group.command(name="list", description="📋 شوف الموارد المنشورة")
    @app_commands.describe(category="فلتر بتصنيف معين (اختياري)")
    @app_commands.choices(category=[app_commands.Choice(name=c, value=c) for c in CATEGORIES])
    async def list_resources(self, interaction: discord.Interaction, category: app_commands.Choice[str] = None):
        resources = db.load("resources")
        approved = [r for r in resources.values() if r["status"] == "approved"]
        if category:
            approved = [r for r in approved if r["category"] == category.value]

        if not approved:
            await interaction.response.send_message("❌ ما كاين حتى ريسورس منشور بهاد الفلتر.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📋 الموارد المنشورة ({len(approved)})",
            color=config.EMBED_COLOR,
        )
        for r in approved[:20]:
            desc = r.get("enhanced_description") or r["description"]
            short_desc = desc[:80] + ("..." if len(desc) > 80 else "")
            embed.add_field(
                name=f"📦 {r['name']} — {r['category']}",
                value=f"{short_desc}\n[دونلود]({r['link']}) | من: {r['author_name']}",
                inline=False,
            )
        if len(approved) > 20:
            embed.set_footer(text=f"كاين {len(approved) - 20} ريسورس آخر — استخدم /resource search")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @resource_group.command(name="search", description="🔍 بحث فـ الموارد بكلمة مفتاحية")
    @app_commands.describe(query="الكلمة المفتاحية")
    async def search(self, interaction: discord.Interaction, query: str):
        resources = db.load("resources")
        q = query.lower()
        matches = [
            r for r in resources.values()
            if r["status"] == "approved" and (
                q in r["name"].lower()
                or q in r["description"].lower()
                or q in (r.get("enhanced_description") or "").lower()
            )
        ]

        if not matches:
            await interaction.response.send_message(f"❌ ما لقيت شي حاجة بـ `{query}`.", ephemeral=True)
            return

        embed = discord.Embed(title=f"🔍 نتائج البحث: {query}", color=config.EMBED_COLOR)
        for r in matches[:15]:
            embed.add_field(
                name=f"📦 {r['name']} — {r['category']}",
                value=f"[دونلود]({r['link']}) | من: {r['author_name']}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @resource_group.command(name="setup", description="⚙️ (أدمن) حدد رومات نظام الموارد: مراجعة / شرح / بانيل")
    @app_commands.describe(
        review_channel="شانل مراجعة الستاف (خاص، ما كيشوفوش الأعضاء)",
        info_channel="روم شرح كيفية استخدام نظام الموارد",
        panel_channel="روم البانيل — كيتبعت فيه زر 📦 قدّم ريسورس ثابت",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_resources(
        self,
        interaction: discord.Interaction,
        review_channel: discord.TextChannel,
        info_channel: discord.TextChannel,
        panel_channel: discord.TextChannel,
    ):
        settings = _settings()
        settings["review_channel_id"] = review_channel.id
        settings["info_channel_id"] = info_channel.id
        settings["panel_channel_id"] = panel_channel.id
        settings.setdefault("publish_channels", {})
        _save_settings(settings)

        # 📖 روم الشرح
        info_embed = discord.Embed(
            title="📦 كيفاش تقترح ريسورس؟",
            description=(
                "هاد السيرفر فيه نظام لنشر الموارد (سكريبتات SA-MP، بوتات ديسكورد، "
                "بلوجينز، gamemodes...) بعد مراجعة من الستاف.\n\n"
                f"**1️⃣** روح لـ {panel_channel.mention} وضغط على 📦 **قدّم ريسورس**.\n"
                "**2️⃣** اختار التصنيف المناسب.\n"
                "**3️⃣** عمر المعلومات (الاسم، الرابط، الفيرجن، الوصف).\n"
                "**4️⃣** الوصف كيتحسّن تلقائياً بالـ AI وكيتبعت للستاف للمراجعة.\n"
                "**5️⃣** إذا تقبل، غادي يتنشر مباشرة فـ الروم المخصصة لتصنيفو، وتوصلك رسالة فـ الخاص.\n\n"
                "ملاحظة: كل تصنيف عندو روم نشر خاص بيه (مثلاً Gamemode فـ روم، Discord Bot فـ روم آخر)."
            ),
            color=config.EMBED_COLOR,
        )
        info_embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        try:
            await info_channel.send(embed=info_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

        # 🖱️ بانيل التقديم
        panel_embed = discord.Embed(
            title="📦 تقديم ريسورس جديد",
            description="ضغط على الزر تحت باش تقترح ريسورس (سكريبت، بوت، بلوجين، gamemode...).",
            color=config.EMBED_COLOR,
        )
        panel_embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        try:
            await panel_channel.send(embed=panel_embed, view=ResourceSubmitPanelView())
        except (discord.Forbidden, discord.HTTPException):
            pass

        await interaction.response.send_message(
            embed=discord.Embed(
                description=(
                    f"✅ تم تفعيل نظام الموارد!\n"
                    f"**مراجعة:** {review_channel.mention}\n"
                    f"**شرح:** {info_channel.mention}\n"
                    f"**بانيل:** {panel_channel.mention}\n\n"
                    f"⚠️ ما نساتيش تحدد شانل نشر لكل تصنيف بـ `/resource setpublish` "
                    f"(مثلاً: Gamemode → روم مخصصة، Discord Bot → روم آخر...)."
                ),
                color=config.SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    @setup_resources.error
    async def setup_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ خاصك صلاحية `Manage Server` باش تستخدم هاد الكوماند.", ephemeral=True
            )

    @resource_group.command(name="setpublish", description="⚙️ (أدمن) حدد روم النشر ديال تصنيف معين")
    @app_commands.describe(
        category="التصنيف",
        channel="الروم لي غادي ينشر فيها هاد التصنيف بعد القبول",
    )
    @app_commands.choices(category=[app_commands.Choice(name=c, value=c) for c in CATEGORIES])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setpublish(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str],
        channel: discord.TextChannel,
    ):
        settings = _settings()
        publish_channels = settings.get("publish_channels", {})
        publish_channels[category.value] = channel.id
        settings["publish_channels"] = publish_channels
        _save_settings(settings)

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ تصنيف **{category.value}** غادي ينشر دابا فـ {channel.mention}.",
                color=config.SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    @setpublish.error
    async def setpublish_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ خاصك صلاحية `Manage Server` باش تستخدم هاد الكوماند.", ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(Resources(bot))
