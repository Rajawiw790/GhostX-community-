"""
Extra commands — Ghostx Community
Hacked/terminal-style profile command
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import random
from datetime import datetime

class Extra(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="profile", description="🖥️ View a member's profile (hacked style)")
    @app_commands.describe(member="The member to view (leave blank for yourself)")
    async def profile(self, interaction: discord.Interaction, member: discord.Member = None):
        if member is None:
            member = interaction.user

        joined_days = (datetime.now() - member.joined_at.replace(tzinfo=None)).days if member.joined_at else 0
        created_days = (datetime.now() - member.created_at.replace(tzinfo=None)).days

        # Build roles list (exclude @everyone)
        roles = [r.mention for r in reversed(member.roles) if r.name != "@everyone"]
        roles_str = " ".join(roles[:5]) if roles else "`No roles`"
        if len(member.roles) - 1 > 5:
            roles_str += f" +{len(member.roles) - 6} more"

        status_map = {
            discord.Status.online: "🟢 Online",
            discord.Status.idle: "🟡 Idle",
            discord.Status.dnd: "🔴 Do Not Disturb",
            discord.Status.offline: "⚫ Offline",
        }
        status = status_map.get(member.status, "⚫ Unknown")

        badges = []
        if member.bot:
            badges.append("🤖 BOT")
        if member == interaction.guild.owner:
            badges.append("👑 OWNER")
        if member.guild_permissions.administrator:
            badges.append("🛡️ ADMIN")
        if member.premium_since:
            badges.append("🚀 BOOSTER")

        # Hacked terminal-style embed
        embed = discord.Embed(
            color=0x00FF41,  # Matrix green
            timestamp=datetime.now()
        )

        embed.set_author(
            name=f"[ GHOSTX SYSTEM — PROFILE SCAN ]",
            icon_url=member.display_avatar.url
        )

        embed.set_thumbnail(url=member.display_avatar.url)

        embed.description = (
            f"```ansi\n"
            f"\u001b[2;32m[ TARGET IDENTIFIED ]\u001b[0m\n"
            f"\u001b[0;32m> USER   : \u001b[0m{member.display_name}\n"
            f"\u001b[0;32m> TAG    : \u001b[0m@{member.name}\n"
            f"\u001b[0;32m> ID     : \u001b[0m{member.id}\n"
            f"\u001b[0;32m> STATUS : \u001b[0m{member.status.name.upper()}\n"
            f"```"
        )

        embed.add_field(
            name="⏱️ Account Created",
            value=f"<t:{int(member.created_at.timestamp())}:D>\n`{created_days} days ago`",
            inline=True
        )
        embed.add_field(
            name="📥 Joined Server",
            value=f"<t:{int(member.joined_at.timestamp())}:D>\n`{joined_days} days ago`" if member.joined_at else "`Unknown`",
            inline=True
        )
        embed.add_field(
            name="🏷️ Top Role",
            value=member.top_role.mention,
            inline=True
        )
        embed.add_field(
            name="🎭 Roles",
            value=roles_str,
            inline=False
        )

        if badges:
            embed.add_field(
                name="🔰 Badges",
                value=" · ".join(badges),
                inline=False
            )

        embed.set_footer(
            text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER} | Scan complete",
            icon_url=self.bot.user.display_avatar.url
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="top", description="🏆 View the top leaderboard")
    async def top(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🏆 Leaderboard", description="Coming soon...", color=config.EMBED_COLOR)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="🎁 Claim your daily reward")
    async def daily(self, interaction: discord.Interaction):
        reward = random.randint(100, 500)
        embed = discord.Embed(
            title="🎁 Daily Reward",
            description=f"You received **{reward}** {config.CURRENCY_EMOJI}",
            color=config.SUCCESS_COLOR
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="balance", description="💰 Check your balance")
    async def balance(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="💰 Balance",
            description=f"Your balance: **1000** {config.CURRENCY_EMOJI}",
            color=config.EMBED_COLOR
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Extra(bot))
