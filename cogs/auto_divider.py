"""
Auto Divider — Ghostx Community
─────────────────────────────────
يبعت صورة فاصل (خط) تلقائياً بعد كل رسالة في روم محددة.

أوامر:
  /divider setup   — عيّن روم + صورة اختيارية
  /divider remove  — ألغِ الروم
  /divider preview — شوف كيف تبان الصورة
  /divider list    — كل الرومات المفعّلة
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import db


def _load() -> dict:
    """{ channel_id_str: { "image_url": str|None } }"""
    return db.load("divider_channels")


def _save(data: dict):
    db.save("divider_channels", data)


class DividerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Cache so we don't hit db on every message
        self._channels: dict[int, str | None] = {}
        self._reload_cache()

    def _reload_cache(self):
        raw = _load()
        self._channels = {int(k): v.get("image_url") for k, v in raw.items()}

    # ── Listener ────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.channel.id not in self._channels:
            return

        image_url = self._channels[message.channel.id]

        try:
            if image_url:
                # Send the custom URL as a plain message (no embed wrapper),
                # and mark it silent so it doesn't ping/notify anyone.
                await message.channel.send(content=image_url, silent=True)
            else:
                # Send the built-in gradient divider file directly, no embed.
                file = discord.File("assets/divider.png", filename="divider.png")
                await message.channel.send(file=file, silent=True)
        except (discord.Forbidden, discord.HTTPException):
            pass

    # ── Slash group ──────────────────────────────────────────────────────────
    divider = app_commands.Group(
        name="divider",
        description="🖼️ نظام الفاصل التلقائي بين الرسائل",
        default_permissions=discord.Permissions(manage_channels=True),
    )

    @divider.command(name="setup", description="✅ فعّل الفاصل التلقائي في روم")
    @app_commands.describe(
        channel="الروم التي ستظهر فيها الصورة بعد كل رسالة",
        image_url="رابط صورة مخصصة (اتركه فارغاً لاستخدام الافتراضية)",
    )
    async def setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        image_url: str = None,
    ):
        raw = _load()
        raw[str(channel.id)] = {"image_url": image_url or None}
        _save(raw)
        self._reload_cache()

        thumb = image_url if image_url else "attachment://Gx.png"
        embed = discord.Embed(
            title="🖼️ تم تفعيل الفاصل التلقائي",
            description=(
                f"**الروم:** {channel.mention}\n"
                f"**الصورة:** {'مخصصة 🔗' if image_url else 'الافتراضية 🎨'}\n\n"
                "سيبعث البوت صورة فاصل بعد كل رسالة في هذا الروم."
            ),
            color=config.SUCCESS_COLOR,
        )
        if not image_url:
            file = discord.File("assets/Gx.png", filename="Gx.png")
            embed.set_image(url="attachment://Gx.png")
            await interaction.response.send_message(embed=embed, file=file, ephemeral=True)
        else:
            embed.set_image(url=image_url)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @divider.command(name="remove", description="❌ ألغِ الفاصل التلقائي من روم")
    @app_commands.describe(channel="الروم التي تريد إلغاء الفاصل منها")
    async def remove(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        raw = _load()
        if str(channel.id) not in raw:
            await interaction.response.send_message(
                f"❌ {channel.mention} غير مفعّل فيها الفاصل.", ephemeral=True
            )
            return
        del raw[str(channel.id)]
        _save(raw)
        self._reload_cache()
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🗑️ تم إلغاء الفاصل",
                description=f"لن يُبعث فاصل في {channel.mention} بعد الآن.",
                color=config.ERROR_COLOR,
            ),
            ephemeral=True,
        )

    @divider.command(name="preview", description="👁️ اعرض الصورة الفاصلة الحالية")
    @app_commands.describe(image_url="رابط صورة للمعاينة (اتركه فارغاً للافتراضية)")
    async def preview(self, interaction: discord.Interaction, image_url: str = None):
        embed = discord.Embed(
            title="👁️ معاينة الفاصل",
            description="هكذا ستبدو الصورة بين الرسائل:",
            color=config.EMBED_COLOR,
        )
        if image_url:
            embed.set_image(url=image_url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            file = discord.File("assets/Gx.png", filename="Gx.png")
            embed.set_image(url="attachment://Gx.png")
            await interaction.response.send_message(embed=embed, file=file, ephemeral=True)

    @divider.command(name="list", description="📋 قائمة الرومات المفعّل فيها الفاصل")
    async def list_channels(self, interaction: discord.Interaction):
        raw = _load()
        if not raw:
            await interaction.response.send_message(
                "❌ لا توجد رومات مفعّلة حالياً.", ephemeral=True
            )
            return

        lines = []
        for cid, val in raw.items():
            ch = interaction.guild.get_channel(int(cid))
            name = ch.mention if ch else f"<#{cid}>"
            img = "مخصصة 🔗" if val.get("image_url") else "افتراضية 🎨"
            lines.append(f"• {name} — {img}")

        embed = discord.Embed(
            title="🖼️ رومات الفاصل التلقائي",
            description="\n".join(lines),
            color=config.EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(DividerCog(bot))
