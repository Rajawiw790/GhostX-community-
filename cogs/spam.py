import asyncio
import time

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
      description="يرسل رسالة من اختيارك",
  )
  @app_commands.describe(
      message="الرسالة التي تريد إرسالها",
      count="عدد الرسائل، أقصى حد 200",
  )
  async def spam(
      self,
      interaction: discord.Interaction,
      message: str,
      count: int = 8,
  ):
    count = max(1, min(count, MAX_MESSAGES))

    # الرد الأول بشكل مخفي لتأكيد بدء العملية
    await interaction.response.send_message(
        _msg(
            "📨",
            "بدء الإرسال",
            **{
                "الرسالة": message,
                "العدد": count,
                "المكان": (
                    interaction.channel.mention if interaction.guild else "DM"
                ),
            },
        ),
        ephemeral=True,
    )

    # إرسال الرسائل في القناة مباشرة
    for _ in range(count):
      try:
        await interaction.channel.send(message)
      except (discord.Forbidden, discord.HTTPException):
        break

      await asyncio.sleep(DELAY)

  @app_commands.command(
      name="spam-duplicate",
      description="يكرر رسالة من اختيارك",
  )
  @app_commands.describe(
      message="الرسالة التي تريد تكرارها",
      count="عدد التكرارات، أقصى حد 200",
  )
  async def spam_duplicate(
      self,
      interaction: discord.Interaction,
      message: str,
      count: int = 5,
  ):
    count = max(1, min(count, MAX_MESSAGES))

    await interaction.response.send_message(
        _msg(
            "🔁",
            "بدء التكرار",
            **{
                "الرسالة": message,
                "العدد": count,
                "المكان": (
                    interaction.channel.mention if interaction.guild else "DM"
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
  await bot.add_cog(Spam(bot))
