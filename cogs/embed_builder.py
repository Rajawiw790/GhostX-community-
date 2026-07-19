import discord
from discord.ext import commands
from discord import app_commands
import config


class EmbedColorModal(discord.ui.Modal, title="تخصيص الإمباد"):
    embed_title = discord.ui.TextInput(
        label="العنوان",
        placeholder="عنوان الإمباد...",
        required=True,
        max_length=256
    )
    embed_description = discord.ui.TextInput(
        label="الوصف",
        placeholder="وصف الإمباد...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=4000
    )
    embed_color = discord.ui.TextInput(
        label="اللون (HEX)",
        placeholder="مثال: 5865F2 أو FF0000",
        required=False,
        max_length=6,
        default="5865F2"
    )
    embed_footer = discord.ui.TextInput(
        label="الفوتر (اختياري)",
        placeholder="نص الفوتر...",
        required=False,
        max_length=200
    )
    embed_image = discord.ui.TextInput(
        label="رابط صورة (اختياري)",
        placeholder="https://...",
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            color = int(self.embed_color.value.strip().lstrip('#') or "5865F2", 16)
        except ValueError:
            color = config.EMBED_COLOR

        embed = discord.Embed(
            title=self.embed_title.value,
            description=self.embed_description.value,
            color=color
        )

        if self.embed_footer.value:
            embed.set_footer(text=self.embed_footer.value)
        else:
            embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

        if self.embed_image.value and self.embed_image.value.startswith("http"):
            embed.set_image(url=self.embed_image.value)

        await interaction.response.send_message(embed=embed)


class EmbedFieldModal(discord.ui.Modal, title="إضافة حقل للإمباد"):
    field_name = discord.ui.TextInput(label="اسم الحقل", max_length=256)
    field_value = discord.ui.TextInput(
        label="قيمة الحقل",
        style=discord.TextStyle.paragraph,
        max_length=1024
    )
    field_inline = discord.ui.TextInput(
        label="في نفس السطر؟ (نعم/لا)",
        placeholder="نعم",
        required=False,
        max_length=3
    )

    def __init__(self, embed_data):
        super().__init__()
        self.embed_data = embed_data

    async def on_submit(self, interaction: discord.Interaction):
        inline = self.field_inline.value.strip().lower() in ("نعم", "yes", "true", "1")
        self.embed_data["fields"].append({
            "name": self.field_name.value,
            "value": self.field_value.value,
            "inline": inline
        })
        embed = build_embed_from_data(self.embed_data)
        view = EmbedBuilderView(self.embed_data)
        await interaction.response.edit_message(
            content="✅ تمت إضافة الحقل! يمكنك الاستمرار في التعديل:",
            embed=embed,
            view=view
        )


def build_embed_from_data(data):
    embed = discord.Embed(
        title=data.get("title", "إمباد"),
        description=data.get("description", ""),
        color=data.get("color", config.EMBED_COLOR)
    )
    if data.get("footer"):
        embed.set_footer(text=data["footer"])
    if data.get("image"):
        embed.set_image(url=data["image"])
    if data.get("thumbnail"):
        embed.set_thumbnail(url=data["thumbnail"])
    for field in data.get("fields", []):
        embed.add_field(
            name=field["name"],
            value=field["value"],
            inline=field.get("inline", False)
        )
    return embed


class EmbedBuilderView(discord.ui.View):
    def __init__(self, embed_data):
        super().__init__(timeout=300)
        self.embed_data = embed_data

    @discord.ui.button(label="➕ إضافة حقل", style=discord.ButtonStyle.primary, emoji="➕")
    async def add_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EmbedFieldModal(self.embed_data)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="📤 إرسال", style=discord.ButtonStyle.success, emoji="📤")
    async def send_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_embed_from_data(self.embed_data)
        await interaction.channel.send(embed=embed)
        await interaction.response.edit_message(content="✅ تم إرسال الإمباد!", embed=None, view=None)

    @discord.ui.button(label="🗑️ إلغاء", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ تم إلغاء بناء الإمباد.", embed=None, view=None)

    @discord.ui.select(
        placeholder="🎨 اختر لون الإمباد",
        options=[
            discord.SelectOption(label="أزرق Discord", value="5865F2", emoji="🔵"),
            discord.SelectOption(label="أخضر", value="00FF00", emoji="🟢"),
            discord.SelectOption(label="أحمر", value="FF0000", emoji="🔴"),
            discord.SelectOption(label="ذهبي", value="FFD700", emoji="🟡"),
            discord.SelectOption(label="برتقالي", value="FFA500", emoji="🟠"),
            discord.SelectOption(label="بنفسجي", value="9B59B6", emoji="🟣"),
            discord.SelectOption(label="وردي", value="FF69B4", emoji="🩷"),
            discord.SelectOption(label="فيروزي", value="1ABC9C", emoji="🩵"),
            discord.SelectOption(label="أسود", value="2C2F33", emoji="⚫"),
            discord.SelectOption(label="أبيض", value="FFFFFF", emoji="⚪"),
        ]
    )
    async def color_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.embed_data["color"] = int(select.values[0], 16)
        embed = build_embed_from_data(self.embed_data)
        await interaction.response.edit_message(embed=embed, view=self)


class EmbedBuilder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="embed-builder", description="🎨 بناء إمباد احترافي خطوة بخطوة")
    @app_commands.default_permissions(manage_messages=True)
    async def embed_builder(self, interaction: discord.Interaction):
        modal = EmbedColorModal()
        await interaction.response.send_modal(modal)

    @app_commands.command(name="embed-advanced", description="🛠️ منشئ إمباد متقدم مع أزرار")
    @app_commands.describe(
        title="عنوان الإمباد",
        description="وصف الإمباد",
        color="اللون HEX (مثال: 5865F2)",
        image="رابط صورة (اختياري)",
        thumbnail="رابط صورة صغيرة (اختياري)",
        footer="نص الفوتر (اختياري)"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def embed_advanced(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        color: str = "5865F2",
        image: str = None,
        thumbnail: str = None,
        footer: str = None
    ):
        try:
            color_int = int(color.strip().lstrip('#'), 16)
        except ValueError:
            color_int = config.EMBED_COLOR

        embed_data = {
            "title": title,
            "description": description,
            "color": color_int,
            "image": image if image and image.startswith("http") else None,
            "thumbnail": thumbnail if thumbnail and thumbnail.startswith("http") else None,
            "footer": footer or f"{config.BOT_NAME} | Dev: {config.DEVELOPER}",
            "fields": []
        }

        embed = build_embed_from_data(embed_data)
        view = EmbedBuilderView(embed_data)

        await interaction.response.send_message(
            content="🛠️ **منشئ الإمباد المتقدم** — يمكنك إضافة حقول أو إرسال الإمباد مباشرة:",
            embed=embed,
            view=view,
            ephemeral=True
        )

    @app_commands.command(name="embed-copy", description="📋 نسخ إمباد من رسالة")
    @app_commands.describe(message_id="أيدي الرسالة التي تحتوي الإمباد")
    @app_commands.default_permissions(manage_messages=True)
    async def embed_copy(self, interaction: discord.Interaction, message_id: str):
        try:
            msg = await interaction.channel.fetch_message(int(message_id))
            if not msg.embeds:
                await interaction.response.send_message("❌ هذه الرسالة لا تحتوي على إمباد!", ephemeral=True)
                return
            embed = msg.embeds[0]
            await interaction.channel.send(embed=embed)
            await interaction.response.send_message("✅ تم نسخ الإمباد!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ خطأ: {e}", ephemeral=True)

    @app_commands.command(name="announce", description="📢 إرسال إعلان احترافي")
    @app_commands.describe(
        title="عنوان الإعلان",
        message="محتوى الإعلان",
        channel="الروم (اختياري)",
        mention="منشن (اختياري مثل @everyone)"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def announce(
        self,
        interaction: discord.Interaction,
        title: str,
        message: str,
        channel: discord.TextChannel = None,
        mention: str = None
    ):
        target = channel or interaction.channel
        embed = discord.Embed(
            title=f"📢 {title}",
            description=message,
            color=config.EMBED_COLOR
        )
        embed.set_author(
            name=interaction.guild.name,
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None
        )
        embed.set_footer(text=f"بواسطة: {interaction.user} | {config.BOT_NAME}")

        content = mention if mention else ""
        await target.send(content=content, embed=embed)
        await interaction.response.send_message(f"✅ تم إرسال الإعلان في {target.mention}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(EmbedBuilder(bot))
