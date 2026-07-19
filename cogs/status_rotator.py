"""
Rotating Bot Status — Ghostx Community
───────────────────────────────────────
Cycles the bot's "Playing ..." status through the list below so the
profile doesn't sit on one static line. Add, remove, or reorder entries
in STATUSES — no other code needs to change.
"""

import itertools
import discord
from discord.ext import commands, tasks

# Add/remove lines here — they rotate in this order, then loop back to the start.
STATUSES = [
    "By Ghostx",
    "Ghostx Community",
    "🎫 /ticket | Support",
    "🎵 /play | Music",
]

ROTATE_EVERY_SECONDS = 20


class StatusRotator(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cycle = itertools.cycle(STATUSES)
        self.rotate.start()

    def cog_unload(self):
        self.rotate.cancel()

    @tasks.loop(seconds=ROTATE_EVERY_SECONDS)
    async def rotate(self):
        await self.bot.change_presence(
            status=discord.Status.online,
            activity=discord.Game(name=next(self._cycle)),
        )

    @rotate.before_loop
    async def before_rotate(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(StatusRotator(bot))
