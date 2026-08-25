import asyncio
import discord
from discord import app_commands
from discord.ext import commands

MAX_MESSAGES = 200
DELAY = 1.0  # تم زيادة التأخير قليلاً لتجنب حظر البوت من ديسكورد (Rate Limit)


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
        description="يرسل رسالة متكررة في القناة، أو لشخص، أو لجميع أعضاء السيرفر في الخاص",
    )
    @app_commands.describe(
        message="الرسالة التي تريد إرسالها",
        count="عدد الرسائل لكل شخص، أقصى حد 200",
        target="شخص معين لإرسال الرسائل لخاصه (اختياري)",
        to_dm="أين تريد إرسال الرسائل؟",
    )
    @app_commands.choices(
        to_dm=[
            app_commands.Choice(name="في القناة الحالية", value="channel"),
            app_commands.Choice(name="في خاصك الشخصي (DM)", value="my_dm"),
            app_commands.Choice(name="لجميع أعضاء السيرفر (Mass DM)", value="all_members"),
        ]
    )
    async def spam(
        self,
        interaction: discord.Interaction,
        message: str,
        count: int = 1,
        target: discord.User = None,
        to_dm: str = "channel",
    ):
        # التحقق من أن الأمر يُستعمل داخل سيرفر إذا تم اختيار إرسال للجميع
        if to_dm == "all_members" and not interaction.guild:
            await interaction.response.send_message(
                "❌ لا يمكنك استخدام خيار جميع الأعضاء إلا من داخل السيرفر!",
                ephemeral=True,
            )
            return

        # تأكيد التفاعل لمنع حدوث خطأ Timeout
        await interaction.response.defer(ephemeral=True)

        count = max(1, min(count, MAX_MESSAGES))

        # الحالة 1: إرسال لشخص محدد
        if target:
            destination_name = f"خاص (DM) لـ {target.mention}"
            await interaction.followup.send(
                _msg("📨", "بدء الإرسال", **{"الرسالة": message, "العدد": count, "المكان": destination_name}),
                ephemeral=True,
            )
            for _ in range(count):
                try:
                    await target.send(message)
                except (discord.Forbidden, discord.HTTPException):
                    break
                await asyncio.sleep(DELAY)

        # الحالة 2: إرسال لجميع أعضاء السيرفر في الخاص
        elif to_dm == "all_members":
            await interaction.followup.send(
                _msg("📨", "بدء الإرسال الجماعي", **{"الرسالة": message, "المكان": "جميع أعضاء السيرفر في الخاص"}),
                ephemeral=True,
            )

            # التأكد من جلب جميع الأعضاء (يتطلب تفعيل Server Members Intent)
            if not interaction.guild.chunked:
                await interaction.guild.fetch_members(limit=None)

            success_count = 0
            fail_count = 0

            for member in interaction.guild.members:
                if member.bot:
                    continue  # تخطي البوتات

                try:
                    # إرسال الرسالة بالعدد المطلوب لكل عضو
                    for _ in range(count):
                        await member.send(message)
                        await asyncio.sleep(DELAY)
                    success_count += 1
                except (discord.Forbidden, discord.HTTPException):
                    # إذا كان العضو قافل الخاص (DMs Closed)
                    fail_count += 1

                # تأخير إضافي بين كل عضو وعضو لتجنب الحظر السريع
                await asyncio.sleep(1.5)

            # إرسال تقرير بالنتيجة بعد الانتهاء
            await interaction.followup.send(
                f"✅ **انتهى الإرسال الجماعي!**\n› تم الإرسال بنجاح لـ: `{success_count}` عضو\n› فشل الإرسال لـ: `{fail_count}` عضو (بسبب إغلاق الخاص)",
                ephemeral=True,
            )

        # الحالة 3: إرسال لخاصك الشخصي
        elif to_dm == "my_dm":
            destination_name = "خاصك الشخصي (DM)"
            await interaction.followup.send(
                _msg("📨", "بدء الإرسال", **{"الرسالة": message, "العدد": count, "المكان": destination_name}),
                ephemeral=True,
            )
            for _ in range(count):
                try:
                    await interaction.user.send(message)
                except (discord.Forbidden, discord.HTTPException):
                    break
                await asyncio.sleep(DELAY)

        # الحالة 4: الإرسال العادي في القناة
        else:
            destination_name = interaction.channel.mention
            await interaction.followup.send(
                _msg("📨", "بدء الإرسال", **{"الرسالة": message, "العدد": count, "المكان": destination_name}),
                ephemeral=True,
            )
            for _ in range(count):
                try:
                    await interaction.channel.send(message)
                except (discord.Forbidden, discord.HTTPException):
                    break
                await asyncio.sleep(DELAY)


async def setup(bot: commands.Bot):
    await bot.add_cog(Spam(bot))
