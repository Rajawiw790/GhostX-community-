import asyncio

import discord
from discord.ext import commands
from discord import app_commands


MAX_MESSAGES = 20
DELAY = 0.4


def _msg(emoji, title, **fields):
    lines = [f"{emoji} **{title}**"]

    for key, value in fields.items():
        lines.append(f"› **{key}:** {value}")

    return "\n".join(lines)


class SpamTest(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="spam-test",
        description="يرسل رسالة اختبار من اختيارك",
    )
    @app_commands.describe(
        message="الرسالة التي تريد إرسالها",
        count="عدد الرسائل، أقصى حد 20",
    )
    async def spam_test(
        self,
        interaction: discord.Interaction,
        message: str,
        count: int = 8,
    ):
        count = max(1, min(count, MAX_MESSAGES))

        await interaction.response.send_message(
            _msg(
                "🧪",
                "بدء الاختبار",
                **{
                    "الرسالة": message,
                    "العدد": count,
                    "المكان": (
                        interaction.channel.mention
                        if interaction.guild
                        else "DM"
                    ),
                },
            ),
            ephemeral=True,
        )

        for i in range(count):
            try:
                await interaction.channel.send(message)
            except (discord.Forbidden, discord.HTTPException):
                break

            await asyncio.sleep(DELAY)

    @app_commands.command(
        name="spam-test-duplicate",
        description="يكرر رسالة من اختيارك لاختبار Duplicate Detection",
    )
    @app_commands.describe(
        message="الرسالة التي تريد تكرارها",
        count="عدد التكرارات، أقصى حد 20",
    )
    async def spam_test_duplicate(
        self,
        interaction: discord.Interaction,
        message: str,
        count: int = 5,
    ):
        count = max(1, min(count, MAX_MESSAGES))

        await interaction.response.send_message(
            _msg(
                "🧪",
                "بدء اختبار Duplicate Detection",
                **{
                    "الرسالة": message,
                    "العدد": count,
                    "المكان": (
                        interaction.channel.mention
                        if interaction.guild
                        else "DM"
                    ),
                },
            ),
            ephemeral=True,
        )

        for _ in range(count):
            try:
                await interaction.channel.send(message)
            except (discord.Forbidden, discord.HTTPException):
                break

            await asyncio.sleep(DELAY)


async def setup(bot: commands.Bot):
    await bot.add_cog(SpamTest(bot))