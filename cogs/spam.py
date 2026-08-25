import asyncio
import discord
from discord import app_commands
from discord.ext import commands

MAX_MESSAGES = 200
DELAY = 0.4


def _msg(emoji, title, **fields):
    lines = [f"{emoji} **{title}**"]
    for key, value in fields.items():
        lines.append(f"› **{key}:** {value}")
    return "\n".join(lines)


class Spam(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="spam",
        description="أمر شخصي لتكرار وإرسال الرسائل في الخاص أو القنوات عبر My Apps",
    )
    @app_commands.describe(
        message="الرسالة التي تريد إرسالها",
        count="عدد الرسائل، أقصى حد 200",
        target="شخص معين لإرسال الرسائل لخاصه (اختياري)",
        to_dm="أين تريد إرسال الرسائل؟",
    )
    @app_commands.choices(
        to_dm=[
            app_commands.Choice(name="في القناة الحالية (إن وجد)", value="channel"),
            app_commands.Choice(name="في خاصك الشخصي (My DM)", value="my_dm"),
        ]
    )
    async def spam(
        self,
        interaction: discord.Interaction,
        message: str,
        count: int = 5,
        target: discord.User = None,
        to_dm: str = "channel",
    ):
        # تأكيد التفاعل لمنع حدوث خطأ Timeout
        await interaction.response.defer(ephemeral=True)

        count = max(1, min(count, MAX_MESSAGES))

        # تحديد وجهة الإرسال للأوامر الشخصية
        if target:
            destination = target
            destination_name = f"خاص (DM) لـ {target.mention}"
        elif to_dm == "my_dm":
            destination = interaction.user
            destination_name = "خاصك الشخصي (DM)"
        else:
            # إذا لم يكن هناك قناة (مثلاً تستخدمه في الـ DM الخاص مع البوت) سيتم الإرسال لخاصك تلقائياً
            destination = interaction.channel if interaction.guild else interaction.user
            destination_name = (
                interaction.channel.mention if interaction.guild else "خاصك الشخصي (DM)"
            )

        # إرسال رسالة التأكيد
        await interaction.followup.send(
            _msg(
                "📨",
                "بدء الإرسال الشخصي",
                **{
                    "الرسالة": message,
                    "العدد": count,
                    "المكان": destination_name,
                },
            ),
            ephemeral=True,
        )

        # حلقة الإرسال
        for _ in range(count):
            try:
                await destination.send(message)
            except (discord.Forbidden, discord.HTTPException):
                break

            await asyncio.sleep(DELAY)


async def setup(bot: commands.Bot):
    await bot.add_cog(Spam(bot))
