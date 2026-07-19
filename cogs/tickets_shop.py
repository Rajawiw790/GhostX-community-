import discord
from discord.ext import commands
from discord import app_commands
import config
import settings
from cogs import emoji_loader
from cogs import panel_settings
from datetime import datetime
import asyncio


# ── أنواع التذاكر (تطابق الصورة) ──────────────────────────────────────────
# الإيموجي الافتراضية Unicode — تُستبدل بالمخصصة عند التشغيل إن وُجدت
TICKET_TYPES = {
    "support":   {
        "label":       "Support",
        "desc":        "General support",
        "color":       0x00B0F4,
        "emoji_key":   "fl_support",
        "emoji_fb":    "💬",
    },
    "report":    {
        "label":       "Report",
        "desc":        "Report a user",
        "color":       0xFF0000,
        "emoji_key":   "fl_ban",
        "emoji_fb":    "🚨",
    },
    "shop":      {
        "label":       "Shop",
        "desc":        "Buy items",
        "color":       0x00FF88,
        "emoji_key":   "fl_vip",
        "emoji_fb":    "🛒",
    },
    "apply":     {
        "label":       "Apply",
        "desc":        "Staff application",
        "color":       0x5865F2,
        "emoji_key":   "fl_staff",
        "emoji_fb":    "📝",
    },
    "partner":   {
        "label":       "Partnership",
        "desc":        "Partnership request",
        "color":       0xFFD700,
        "emoji_key":   "fl_check",
        "emoji_fb":    "🤝",
    },
    "other":     {
        "label":       "Other",
        "desc":        "Other inquiries",
        "color":       0xAAAAAA,
        "emoji_key":   "fl_arrow_green",
        "emoji_fb":    "❓",
    },
}


# ── Modal: يكتب المستخدم تفاصيل طلبه ──────────────────────────────────────
class ShopProblemModal(discord.ui.Modal, title="📝 اشرح طلبك"):
    def __init__(self, ticket_type: str):
        super().__init__()
        self.ticket_type = ticket_type
        info = TICKET_TYPES.get(ticket_type, TICKET_TYPES["other"])
        label = panel_settings.get(f"type_{ticket_type}_label") or info["label"]
        self.problem = discord.ui.TextInput(
            label=f"اشرح طلبك — {label}",
            style=discord.TextStyle.paragraph,
            placeholder="اكتب تفاصيل طلبك هنا بوضوح...",
            min_length=5,
            max_length=1000,
        )
        self.add_item(self.problem)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await create_shop_ticket(interaction, self.ticket_type, self.problem.value)


# ── Select Menu: اختيار نوع التذكرة ────────────────────────────────────────
def _resolve_emoji(ticket_type: str, info: dict):
    """ارجع الإيموجي المناسب للنوع: مخصص من panel_settings > مخصص من fl_ > افتراضي."""
    custom_str = panel_settings.get(f"type_{ticket_type}_emoji")
    if custom_str:
        try:
            if custom_str.startswith("<"):
                return discord.PartialEmoji.from_str(custom_str)
            return custom_str
        except Exception:
            pass
    custom_emoji = emoji_loader.get_obj(info["emoji_key"])
    return custom_emoji if custom_emoji else info["emoji_fb"]


class TicketTypeSelect(discord.ui.Select):
    def __init__(self):
        options = []
        for key, info in TICKET_TYPES.items():
            label = panel_settings.get(f"type_{key}_label") or info["label"]
            desc  = panel_settings.get(f"type_{key}_desc")  or info["desc"]
            emoji = _resolve_emoji(key, info)

            options.append(
                discord.SelectOption(
                    label=label,
                    description=desc,
                    value=key,
                    emoji=emoji,
                )
            )

        super().__init__(
            placeholder="Choose a ticket type...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="shop_direct_select",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ShopProblemModal(self.values[0]))


class ShopTicketDirectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect())


# ── إنشاء التيكت ────────────────────────────────────────────────────────────
async def create_shop_ticket(
    interaction: discord.Interaction, ticket_type: str, problem_text: str
):
    info = TICKET_TYPES.get(ticket_type, TICKET_TYPES["other"])
    label = panel_settings.get(f"type_{ticket_type}_label") or info["label"]
    emoji_display = panel_settings.get(f"type_{ticket_type}_emoji") or info["emoji_fb"]
    category_id = getattr(config, "SHOP_TICKET_CATEGORY_ID", None)
    category    = interaction.guild.get_channel(category_id) if category_id else None

    if not category:
        await interaction.followup.send(
            "❌ لم يتم إعداد نظام تذاكر المتجر! استخدم `/ticket-shop-setup`",
            ephemeral=True,
        )
        return

    for ch in category.text_channels:
        if ch.topic and ch.topic.startswith(f"SHOP:{interaction.user.id}:{ticket_type}"):
            await interaction.followup.send(
                f"⚠️ لديك تذكرة **{label}** مفتوحة: {ch.mention}",
                ephemeral=True,
            )
            return

    support_role_id = getattr(config, "SHOP_SUPPORT_ROLE_ID", None)
    support_role    = interaction.guild.get_role(support_role_id) if support_role_id else None

    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        interaction.guild.me:  discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
    }
    if support_role:
        overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    channel_name = f"🎫-{ticket_type}-{interaction.user.name}"[:100]
    ticket_channel = await category.create_text_channel(
        name=channel_name,
        topic=f"SHOP:{interaction.user.id}:{ticket_type}",
        overwrites=overwrites,
    )

    # إيموجي الحسهم المتحرك للتزيين
    e_arrow = emoji_loader.get("fl_arrow_blue") or "➤"
    e_check = emoji_loader.get("fl_check")      or "✅"

    embed = discord.Embed(
        title=f"{emoji_display} {label} — تذكرة جديدة",
        color=info["color"],
        timestamp=datetime.now(),
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)

    shop_banner = settings.get("shop_banner_url") or getattr(config, "SHOP_TICKET_BANNER_URL", None)
    if shop_banner:
        embed.set_image(url=shop_banner)

    embed.add_field(name="👤 فاتح التذكرة", value=interaction.user.mention, inline=True)
    embed.add_field(name="📅 الوقت", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)
    embed.add_field(name="📌 نوع الطلب", value=f"{emoji_display} {label}", inline=True)
    embed.add_field(name="📝 تفاصيل الطلب", value=f"```{problem_text}```", inline=False)
    embed.set_footer(text=panel_settings.render(panel_settings.get("shop_footer")) or f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

    note_embed = discord.Embed(
        description=(
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"**مرحباً {interaction.user.mention}** 👋\n\n"
            f"{e_arrow} تم فتح تذكرتك وإرسال تفاصيل طلبك.\n"
            f"{e_arrow} سيردّ عليك أحد أعضاء الفريق في أقرب وقت.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=info["color"],
    )

    mention_str = interaction.user.mention
    if support_role:
        mention_str += f" {support_role.mention}"

    await ticket_channel.send(content=mention_str, embed=embed, view=ShopTicketControlView())
    await ticket_channel.send(embed=note_embed)

    await interaction.followup.send(
        f"{e_check} تم فتح تذكرتك: {ticket_channel.mention}", ephemeral=True
    )


# ── أزرار التحكم داخل تيكت المتجر (تُبنى ديناميكياً حسب panel_settings) ────
class ShopTicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        close_emoji = emoji_loader.get_obj("fl_locked") or panel_settings.get("shop_close_emoji")
        claim_emoji = emoji_loader.get_obj("fl_check")  or panel_settings.get("shop_claim_emoji")
        done_emoji  = emoji_loader.get_obj("fl_check")  or panel_settings.get("shop_done_emoji")

        close_btn = discord.ui.Button(
            label=panel_settings.get("shop_close_label"),
            style=discord.ButtonStyle.danger,
            custom_id="shop_ctrl_close",
            emoji=close_emoji,
        )
        close_btn.callback = self.close_btn
        self.add_item(close_btn)

        claim_btn = discord.ui.Button(
            label=panel_settings.get("shop_claim_label"),
            style=discord.ButtonStyle.success,
            custom_id="shop_ctrl_claim",
            emoji=claim_emoji,
        )
        claim_btn.callback = self.claim_btn
        self.add_item(claim_btn)

        done_btn = discord.ui.Button(
            label=panel_settings.get("shop_done_label"),
            style=discord.ButtonStyle.primary,
            custom_id="shop_ctrl_done",
            emoji=done_emoji,
        )
        done_btn.callback = self.done_btn
        self.add_item(done_btn)

    async def close_btn(self, interaction: discord.Interaction):
        e_warning = emoji_loader.get("fl_warning") or "⚠️"
        embed = discord.Embed(
            title=f"{e_warning} سيتم إغلاق التذكرة",
            description="حذف خلال **5 ثواني**...",
            color=config.WARNING_COLOR,
        )
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
        except Exception:
            pass

    async def claim_btn(self, interaction: discord.Interaction):
        e_check = emoji_loader.get("fl_check") or "✅"
        embed = discord.Embed(
            title=f"{e_check} تم الاستلام",
            description=f"{interaction.user.mention} سيتولى معالجة طلبك 👋",
            color=config.SUCCESS_COLOR,
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=panel_settings.render(panel_settings.get("shop_footer")) or f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

    async def done_btn(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ ليس لديك صلاحية!", ephemeral=True)
            return
        e_check = emoji_loader.get("fl_check") or "✅"
        embed = discord.Embed(
            title=f"{e_check} تم تنفيذ الطلب",
            description=(
                f"تم التنفيذ بواسطة {interaction.user.mention}\n"
                "سيتم الإغلاق خلال **10 ثواني**..."
            ),
            color=config.SUCCESS_COLOR,
        )
        embed.set_footer(text=panel_settings.render(panel_settings.get("shop_footer")) or f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(10)
        try:
            await interaction.channel.delete()
        except Exception:
            pass


# ── Cog ─────────────────────────────────────────────────────────────────────
class TicketsShop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ticket-shop-setup", description="🛒 إعداد نظام تذاكر المتجر")
    @app_commands.describe(
        channel="روم لإرسال رسالة الاختيار فيه",
        category="كاتيجوري التذاكر",
        support_role="رتبة فريق الدعم",
        banner_url="رابط بانر (اختياري)",
    )
    @app_commands.default_permissions(administrator=True)
    async def ticket_shop_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        category: discord.CategoryChannel,
        support_role: discord.Role,
        banner_url: str = None,
    ):
        config.SHOP_TICKET_CATEGORY_ID = category.id
        config.SHOP_SUPPORT_ROLE_ID    = support_role.id
        if banner_url:
            settings.set("shop_banner_url", banner_url)
            config.SHOP_TICKET_BANNER_URL = banner_url
        saved_banner = settings.get("shop_banner_url") or getattr(config, "SHOP_TICKET_BANNER_URL", None)

        e_arrow = emoji_loader.get("fl_arrow_blue") or "➤"

        default_desc = (
            f"{e_arrow} اختر نوع طلبك من القائمة أدناه\n"
            f"{e_arrow} ستظهر نافذة لكتابة تفاصيل طلبك\n"
            f"{e_arrow} سيرد فريق الدعم عليك في أقرب وقت"
        )
        title = panel_settings.render(panel_settings.get("shop_title"))
        description = panel_settings.render(panel_settings.get("shop_description")) or default_desc
        footer = panel_settings.render(panel_settings.get("shop_footer")) or f"{config.BOT_NAME} | Dev: {config.DEVELOPER}"

        embed = discord.Embed(
            title=title,
            description=description,
            color=config.EMBED_COLOR,
        )
        embed.add_field(name="👥 فريق الدعم", value=support_role.mention, inline=True)
        embed.add_field(name="📂 الكاتيجوري", value=category.mention, inline=True)
        if banner_url and banner_url.startswith("http"):
            embed.set_image(url=banner_url)
        elif saved_banner:
            embed.set_image(url=saved_banner)
        embed.set_footer(text=footer)

        await channel.send(embed=embed, view=ShopTicketDirectView())

        success = discord.Embed(
            title="✅ تم إعداد نظام التذاكر",
            description=(
                f"• الروم: {channel.mention}\n"
                f"• الكاتيجوري: {category.mention}\n"
                f"• رتبة الدعم: {support_role.mention}\n"
                f"• البانر: {'✅' if saved_banner else '❌ لا يوجد'}"
            ),
            color=config.SUCCESS_COLOR,
        )
        success.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=success, ephemeral=True)

    @app_commands.command(name="ticket-shop-banner", description="🖼️ تغيير بانر تذاكر المتجر")
    @app_commands.describe(url="رابط الصورة")
    @app_commands.default_permissions(administrator=True)
    async def ticket_shop_banner(self, interaction: discord.Interaction, url: str):
        if not url.startswith("http"):
            await interaction.response.send_message("❌ رابط غير صحيح!", ephemeral=True)
            return
        config.SHOP_TICKET_BANNER_URL = url
        settings.set("shop_banner_url", url)
        embed = discord.Embed(title="🖼️ تم تغيير البانر", color=config.SUCCESS_COLOR)
        embed.set_image(url=url)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ticket-shop-customize", description="🛠️ تخصيص عنوان/محتوى/فوتر رسالة تذاكر المتجر")
    @app_commands.describe(
        title="عنوان الرسالة (اختياري، تقدر تستعمل {server})",
        description="محتوى الرسالة (اختياري)",
        footer="نص الفوتر (اختياري، تقدر تستعمل {bot}/{dev})",
    )
    @app_commands.default_permissions(administrator=True)
    async def ticket_shop_customize(
        self,
        interaction: discord.Interaction,
        title: str = None,
        description: str = None,
        footer: str = None,
    ):
        if not any([title, description, footer]):
            await interaction.response.send_message("❌ خاصك تعطي على الأقل قيمة وحدة (عنوان/محتوى/فوتر)!", ephemeral=True)
            return

        panel_settings.set_values(shop_title=title, shop_description=description, shop_footer=footer)

        embed = discord.Embed(
            title="✅ تم تحديث تخصيص Ticket Shop",
            description=(
                "غادي يتطبق هاد التغيير فالمرة الجاية لي تدير فيها `/ticket-shop-setup` "
                "باش تنشر الرسالة الجديدة بالبانل ديال الاختيار."
            ),
            color=config.SUCCESS_COLOR,
        )
        if title:
            embed.add_field(name="📌 العنوان", value=title, inline=False)
        if description:
            embed.add_field(name="📝 المحتوى", value=description[:1000], inline=False)
        if footer:
            embed.add_field(name="🔻 الفوتر", value=footer, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ticket-shop-buttons-customize", description="🔘 تخصيص نص وإيموجي أزرار تذاكر المتجر")
    @app_commands.describe(
        button="الزر لي بغيتي تبدل فيه",
        label="النص الجديد للزر (اختياري)",
        emoji="الإيموجي الجديد للزر (اختياري، مثال: 🔒 أو <:name:id>)",
    )
    @app_commands.choices(button=[
        app_commands.Choice(name="إغلاق (Close)", value="close"),
        app_commands.Choice(name="استلام (Claim)", value="claim"),
        app_commands.Choice(name="تم التنفيذ (Done)", value="done"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def ticket_shop_buttons_customize(
        self,
        interaction: discord.Interaction,
        button: app_commands.Choice[str],
        label: str = None,
        emoji: str = None,
    ):
        if not label and not emoji:
            await interaction.response.send_message("❌ خاصك تعطي على الأقل نص جديد ولا إيموجي!", ephemeral=True)
            return

        key = button.value
        panel_settings.set_values(**{
            f"shop_{key}_label": label,
            f"shop_{key}_emoji": emoji,
        })

        embed = discord.Embed(
            title="✅ تم تحديث الزر",
            description=(
                f"الزر **{button.name}** تبدل.\n"
                "غادي يبان هاد التغيير فالتذاكر الجداد لي غادي يتفتحو (ماشي القديمين)."
            ),
            color=config.SUCCESS_COLOR,
        )
        if label:
            embed.add_field(name="النص", value=label, inline=True)
        if emoji:
            embed.add_field(name="الإيموجي", value=emoji, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


    @app_commands.command(name="ticket-shop-types-customize", description="📋 تخصيص نوع من أنواع التذكرة فالقائمة المنسدلة")
    @app_commands.describe(
        type="نوع التذكرة لي بغيتي تبدل فيه",
        label="الاسم الجديد (اختياري)",
        description="الوصف الجديد اللي كيبان تحت الاسم (اختياري)",
        emoji="الإيموجي الجديد (اختياري، مثال: 🛒 أو <:name:id>)",
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="Support", value="support"),
        app_commands.Choice(name="Report", value="report"),
        app_commands.Choice(name="Shop", value="shop"),
        app_commands.Choice(name="Apply", value="apply"),
        app_commands.Choice(name="Partnership", value="partner"),
        app_commands.Choice(name="Other", value="other"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def ticket_shop_types_customize(
        self,
        interaction: discord.Interaction,
        type: app_commands.Choice[str],
        label: str = None,
        description: str = None,
        emoji: str = None,
    ):
        if not any([label, description, emoji]):
            await interaction.response.send_message("❌ خاصك تعطي على الأقل قيمة وحدة (اسم/وصف/إيموجي)!", ephemeral=True)
            return

        key = type.value
        panel_settings.set_values(**{
            f"type_{key}_label": label,
            f"type_{key}_desc": description,
            f"type_{key}_emoji": emoji,
        })

        embed = discord.Embed(
            title="✅ تم تحديث نوع التذكرة",
            description=(
                f"النوع **{type.name}** تبدل.\n"
                "غادي يبان هاد التغيير فالمرة الجاية لي تدير فيها `/ticket-shop-setup` "
                "باش تنشر البانل الجديد بالقائمة المحدّثة."
            ),
            color=config.SUCCESS_COLOR,
        )
        if label:
            embed.add_field(name="الاسم", value=label, inline=True)
        if description:
            embed.add_field(name="الوصف", value=description, inline=True)
        if emoji:
            embed.add_field(name="الإيموجي", value=emoji, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(TicketsShop(bot))
