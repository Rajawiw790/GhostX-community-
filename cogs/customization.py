import discord
from discord.ext import commands
from discord import app_commands
import config
import settings


THEMES = {
    "default": {
        "name": "🔵 Discord الافتراضي",
        "color": 0x5865F2,
        "success": 0x57F287,
        "error": 0xED4245,
        "warning": 0xFEE75C
    },
    "gold": {
        "name": "🏆 ذهبي ملكي",
        "color": 0xFFD700,
        "success": 0x00FF00,
        "error": 0xFF4500,
        "warning": 0xFFA500
    },
    "red": {
        "name": "🔴 أحمر نار",
        "color": 0xFF0000,
        "success": 0x00FF00,
        "error": 0x8B0000,
        "warning": 0xFF8C00
    },
    "green": {
        "name": "🟢 أخضر طبيعة",
        "color": 0x2ECC71,
        "success": 0x27AE60,
        "error": 0xE74C3C,
        "warning": 0xF39C12
    },
    "purple": {
        "name": "💜 بنفسجي ملكي",
        "color": 0x9B59B6,
        "success": 0x2ECC71,
        "error": 0xE74C3C,
        "warning": 0xF1C40F
    },
    "cyan": {
        "name": "🩵 فيروزي",
        "color": 0x1ABC9C,
        "success": 0x2ECC71,
        "error": 0xE74C3C,
        "warning": 0xF39C12
    },
    "black": {
        "name": "⚫ أسود فاخر",
        "color": 0x2C2F33,
        "success": 0x43B581,
        "error": 0xF04747,
        "warning": 0xFAA61A
    },
    "pink": {
        "name": "🩷 وردي",
        "color": 0xFF69B4,
        "success": 0x00FF7F,
        "error": 0xFF0000,
        "warning": 0xFF8C00
    }
}


class ThemeSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.select(
        placeholder="🎨 اختر ثيم البوت",
        options=[
            discord.SelectOption(label="🔵 Discord الافتراضي", value="default", description="الثيم الأزرق الكلاسيكي"),
            discord.SelectOption(label="🏆 ذهبي ملكي", value="gold", description="ثيم ذهبي فاخر"),
            discord.SelectOption(label="🔴 أحمر نار", value="red", description="ثيم أحمر قوي"),
            discord.SelectOption(label="🟢 أخضر طبيعة", value="green", description="ثيم أخضر هادئ"),
            discord.SelectOption(label="💜 بنفسجي ملكي", value="purple", description="ثيم بنفسجي أنيق"),
            discord.SelectOption(label="🩵 فيروزي", value="cyan", description="ثيم فيروزي منعش"),
            discord.SelectOption(label="⚫ أسود فاخر", value="black", description="ثيم أسود داكن"),
            discord.SelectOption(label="🩷 وردي", value="pink", description="ثيم وردي جميل"),
        ]
    )
    async def theme_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        theme_key = select.values[0]
        theme = THEMES[theme_key]

        config.EMBED_COLOR = theme["color"]
        config.SUCCESS_COLOR = theme["success"]
        config.ERROR_COLOR = theme["error"]
        config.WARNING_COLOR = theme["warning"]

        embed = discord.Embed(
            title=f"✅ تم تغيير الثيم إلى {theme['name']}",
            description="تم تحديث ألوان البوت بنجاح! سيظهر الثيم الجديد في جميع الأوامر.",
            color=theme["color"]
        )
        embed.add_field(name="🎨 اللون الرئيسي", value=f"`#{hex(theme['color'])[2:].upper()}`", inline=True)
        embed.add_field(name="✅ لون النجاح", value=f"`#{hex(theme['success'])[2:].upper()}`", inline=True)
        embed.add_field(name="❌ لون الخطأ", value=f"`#{hex(theme['error'])[2:].upper()}`", inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

        await interaction.response.edit_message(embed=embed, view=None)


class BotNameModal(discord.ui.Modal, title="تغيير اسم ومعلومات البوت"):
    bot_name = discord.ui.TextInput(
        label="اسم البوت",
        placeholder="Ghostx Community",
        default="Ghostx Community",
        max_length=50
    )
    server_name = discord.ui.TextInput(
        label="اسم السيرفر",
        placeholder="Ghostx Community",
        default="Ghostx Community",
        max_length=50
    )
    developer_name = discord.ui.TextInput(
        label="اسم المطور",
        placeholder="GHOSTX",
        default="GHOSTX",
        max_length=30
    )

    async def on_submit(self, interaction: discord.Interaction):
        config.BOT_NAME = self.bot_name.value
        config.SERVER_NAME = self.server_name.value
        config.DEVELOPER = self.developer_name.value

        embed = discord.Embed(
            title="✅ تم تحديث معلومات البوت",
            color=config.SUCCESS_COLOR
        )
        embed.add_field(name="🤖 اسم البوت", value=config.BOT_NAME, inline=True)
        embed.add_field(name="🌐 اسم السيرفر", value=config.SERVER_NAME, inline=True)
        embed.add_field(name="👑 المطور", value=config.DEVELOPER, inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class Customization(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="theme", description="🎨 تغيير ثيم البوت وألوانه")
    @app_commands.default_permissions(administrator=True)
    async def theme(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎨 تخصيص ثيم البوت",
            description="اختر الثيم الذي يناسب سيرفرك من القائمة أدناه:",
            color=config.EMBED_COLOR
        )
        for key, t in THEMES.items():
            embed.add_field(
                name=t["name"],
                value=f"`#{hex(t['color'])[2:].upper()}`",
                inline=True
            )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

        view = ThemeSelectView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="bot-info-set", description="⚙️ تخصيص اسم ومعلومات البوت")
    @app_commands.default_permissions(administrator=True)
    async def set_botinfo(self, interaction: discord.Interaction):
        modal = BotNameModal()
        await interaction.response.send_modal(modal)

    @app_commands.command(name="color-set", description="🖌️ تعيين لون مخصص للإمباد")
    @app_commands.describe(color="اللون HEX (مثال: 5865F2)")
    @app_commands.default_permissions(administrator=True)
    async def color_set(self, interaction: discord.Interaction, color: str):
        try:
            color_int = int(color.strip().lstrip('#'), 16)
            config.EMBED_COLOR = color_int
            embed = discord.Embed(
                title="✅ تم تغيير اللون",
                description=f"تم تعيين اللون الرئيسي إلى `#{color.upper().lstrip('#')}`",
                color=color_int
            )
            embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except ValueError:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="❌ لون غير صحيح! استخدم HEX مثل: `FF0000` أو `5865F2`",
                    color=config.ERROR_COLOR
                ),
                ephemeral=True
            )

    @app_commands.command(name="server-config", description="📋 عرض إعدادات البوت الحالية")
    @app_commands.default_permissions(administrator=True)
    async def server_config(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"⚙️ إعدادات {config.BOT_NAME}",
            color=config.EMBED_COLOR
        )
        embed.add_field(name="🤖 اسم البوت", value=config.BOT_NAME, inline=True)
        embed.add_field(name="🌐 اسم السيرفر", value=config.SERVER_NAME, inline=True)
        embed.add_field(name="👑 المطور", value=config.DEVELOPER, inline=True)
        embed.add_field(name="🎨 اللون الرئيسي", value=f"`#{hex(config.EMBED_COLOR)[2:].upper()}`", inline=True)
        embed.add_field(name="✅ لون النجاح", value=f"`#{hex(config.SUCCESS_COLOR)[2:].upper()}`", inline=True)
        embed.add_field(name="❌ لون الخطأ", value=f"`#{hex(config.ERROR_COLOR)[2:].upper()}`", inline=True)
        embed.add_field(name="👋 روم الترحيب", value=f"<#{config.WELCOME_CHANNEL_ID}>", inline=True)
        embed.add_field(name="✅ روم التحقق", value=f"<#{config.VERIFY_CHANNEL_ID}>", inline=True)
        embed.add_field(name="🎫 كاتيجوري التذاكر", value=f"<#{config.TICKET_CATEGORY_ID}>", inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="panel-banner", description="🖼️ أمر عام لتغيير بانر أي رسالة فالبوت (ترحيب/تحقق/متجر)")
    @app_commands.describe(
        target="الرسالة اللي بغيتي تبدل البانر ديالها",
        url="رابط الصورة المباشر (jpg/png) | أرسل 'reset' للرجوع للافتراضي",
    )
    @app_commands.choices(target=[
        app_commands.Choice(name="🌟 الترحيب (Welcome)", value="welcome"),
        app_commands.Choice(name="✅ التحقق (Verify)", value="verify"),
        app_commands.Choice(name="🛒 تذاكر المتجر (Ticket Shop)", value="shop"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def panel_banner(
        self,
        interaction: discord.Interaction,
        target: app_commands.Choice[str],
        url: str,
    ):
        key_map = {
            "welcome": "welcome_bg_url",
            "verify":  "verify_banner_url",
            "shop":    "shop_banner_url",
        }
        settings_key = key_map[target.value]

        if url.lower() == "reset":
            settings.set(settings_key, "")
            await interaction.response.send_message(
                f"🔄 تم إعادة بانر **{target.name}** للافتراضي.", ephemeral=True
            )
            return

        if not url.startswith("http"):
            await interaction.response.send_message("❌ رابط غير صحيح!", ephemeral=True)
            return

        settings.set(settings_key, url)
        # نحدّث كذلك متغير config مباشرة للتوافق مع باقي الكود فنفس التشغيلة
        if target.value == "verify":
            config.VERIFY_BANNER_URL = url
        elif target.value == "shop":
            config.SHOP_TICKET_BANNER_URL = url

        embed = discord.Embed(title=f"✅ تم تغيير بانر {target.name}", color=config.SUCCESS_COLOR)
        embed.set_image(url=url)
        embed.set_footer(text=(
            "استعمل /verify-setup أو /ticket-shop-setup أو /welcome-test باش تشوف التغيير"
        ))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="prefix-info", description="ℹ️ معلومات عن أوامر البوت")
    async def prefix_info(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"ℹ️ {config.BOT_NAME} — معلومات",
            description="جميع أوامر البوت تعمل بنظام **Slash Commands** `/`",
            color=config.EMBED_COLOR
        )
        embed.add_field(
            name="📂 الكاتيجوريات",
            value=(
                "👑 **الإدارة** — ban, kick, mute, clear...\n"
                "🎫 **التذاكر** — ticket-setup, ticket-close...\n"
                "✅ **التحقق** — verify-setup\n"
                "🎉 **السحوبات** — giveaway-start\n"
                "🎵 **الموسيقى** — play, skip, queue...\n"
                "🎨 **الإمباد** — embed-builder, embed-advanced\n"
                "⚙️ **التخصيص** — theme, color-set\n"
                "🎮 **ترفيه** — avatar, roll, 8ball..."
            ),
            inline=False
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Customization(bot))
