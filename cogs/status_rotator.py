"""
Rotating Bot Status — Ghostx Community
───────────────────────────────────────
Rotates through different activities AND types automatically.
Add more items in ACTIVITIES. No other code needs to change.
"""

import itertools
import random
import discord
from discord.ext import commands, tasks

# زيد هنا كلشي لي بغيتي. تقدر تزيد 100 سطر
ACTIVITIES = [
    "Ghostx Community",
    "By Ghostx",
    "online 24/7",
    "GhostX the best",
    "1773+ Members",
    "Discord Server",
    "Games 24/7",
    "Free Fire Tournaments",
    "eFootball Matches",
    "PUBG Rooms",
    "Valorant Clutches",
    "CS2 Ranks",
    "Roblox Games",
    "SA-MP Server",
    "Music",
    "YouTube Videos",
]

# الأنواع اللي غادي يدور بينهم
ACTIVITY_TYPES = [
    discord.ActivityType.playing,     # Playing
    discord.ActivityType.watching,    # Watching
    discord.ActivityType.listening,   # Listening to
    discord.ActivityType.streaming,   # Streaming
    discord.ActivityType.competing,   # Competing in
]

ROTATE_EVERY_SECONDS = 5

class StatusRotator(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rotate.start()

    def cog_unload(self):
        self.rotate.cancel()

    @tasks.loop(seconds=ROTATE_EVERY_SECONDS)
    async def rotate(self):
        # كل مرة كيختار نوع و اسم عشوائي
        activity_name = random.choice(ACTIVITIES)
        activity_type = random.choice(ACTIVITY_TYPES)
        
        # إلا كان Streaming خاص ليان
        if activity_type == discord.ActivityType.streaming:
            activity = discord.Streaming(name=activity_name, url="https://twitch.tv/ghostx")
        else:
            activity = discord.Activity(type=activity_type, name