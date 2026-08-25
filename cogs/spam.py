import asyncio

import discord
from discord.ext import commands
from discord import app_commands


def _msg(emoji, title, **fields):
    lines = [f"{emoji} **{title}**"]
    for k, v in fields.items():
        lines.append(f"› **{k}:** {v}")
    return "\n".join(lines)


class SpamTest(commands.Cog):
    """
    Owner-only testing utility. Sends a controlled burst of test messages
    in the current channel so you can verify anti_spam.py actually
    triggers (timeout, purge, log message) on your own server.

    NOT a real spam tool: capped at 20 messages, owner-only, and meant
    to be deleted/disabled once you're done testing.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="spam-test",
        description="[أونر فقط] يبعت رسائل تجريبية باش يختبر نظام مكافحة السبام",
    )
    @app_commands.describe(count="عدد الرسائل التجريبية (أقصى حد 20)")
    async def spam_test(self, interaction: discord.Interaction, count: int = 8):
        if interaction.user.id != interaction.guild.owner_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                _msg("⛔", "ممنوع", **{"السبب": "هاد الأمر خاص بالأونر أو الأدمن فقط"}),
                ephemeral=True,
            )
            return

        count = max(1, min(count, 20))  # hard cap, this is a test tool not a spam tool

        await interaction.response.send_message(
            _msg("🧪", "بدء الاختبار", **{"عدد الرسائل": count, "القناة": interaction.channel.mention}),
            ephemeral=True,
        )

        for i in range(count):
            try:
                await interaction.channel.send(f"test message {i + 1}/{count}")
            except discord.HTTPException:
                break
            await asyncio.sleep(0.4)  # small delay so we don't get globally rate-limited

    @app_commands.command(
        name="spam-test-duplicate",
        description="[أونر فقط] يبعت نفس الرسالة بالتكرار باش يختبر duplicate detection",
    )
    @app_commands.describe(count="عدد التكرارات (أقصى حد 20)")
    async def spam_test_duplicate(self, interaction: discord.Interaction, count: int = 5):
        if interaction.user.id != interaction.guild.owner_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                _msg("⛔", "ممنوع", **{"السبب": "هاد الأمر خاص بالأونر أو الأدمن فقط"}),
                ephemeral=True,
            )
            return

        count = max(1, min(count, 20))

        await interaction.response.send_message(
            _msg("🧪", "بدء اختبار التكرار", **{"عدد الرسائل": count}),
            ephemeral=True,
        )

        for _ in range(count):
            try:
                await interaction.channel.send("same message")
            except discord.HTTPException:
                break
            await asyncio.sleep(0.4)


async def setup(bot: commands.Bot):
    await bot.add_cog(SpamTest(bot))
