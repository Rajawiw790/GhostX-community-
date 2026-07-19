import discord
from discord.ext import commands
from discord import app_commands
import config
import asyncio

active_polls: dict[int, dict] = {}

def make_bar(votes: int, total: int, length: int = 20) -> str:
    if total == 0:
        filled = 0
    else:
        filled = round((votes / total) * length)
    bar = "█" * filled + "░" * (length - filled)
    pct = round((votes / total) * 100) if total > 0 else 0
    return f"`{bar}` {pct}%"

class PollView(discord.ui.View):
    def __init__(self, options: list[str], poll_id: int):
        super().__init__(timeout=None)
        self.poll_id = poll_id
        for i, opt in enumerate(options):
            btn = discord.ui.Button(
                label=opt[:80],
                style=discord.ButtonStyle.primary,
                custom_id=f"poll_{poll_id}_{i}",
                row=i // 3
            )
            btn.callback = self.vote_callback
            self.add_item(btn)

    async def vote_callback(self, interaction: discord.Interaction):
        poll = active_polls.get(self.poll_id)
        if not poll:
            await interaction.response.send_message("❌ هذا التصويت انتهى!", ephemeral=True)
            return

        custom_id = interaction.data["custom_id"]
        opt_index = int(custom_id.split("_")[-1])
        user_id = interaction.user.id

        prev = poll["user_votes"].get(user_id)
        if prev == opt_index:
            await interaction.response.send_message("❌ صوّتت على هذا الخيار مسبقاً!", ephemeral=True)
            return

        if prev is not None:
            poll["votes"][prev] = max(0, poll["votes"][prev] - 1)

        poll["votes"][opt_index] += 1
        poll["user_votes"][user_id] = opt_index

        await self._update_message(interaction, poll)

    async def _update_message(self, interaction: discord.Interaction, poll: dict):
        total = sum(poll["votes"])
        desc = f"**{poll['question']}**\n\n"
        for i, opt in enumerate(poll["options"]):
            v = poll["votes"][i]
            desc += f"**{opt}**\n{make_bar(v, total)} — {v} صوت\n\n"
        desc += f"📊 مجموع الأصوات: **{total}**"

        embed = discord.Embed(
            title="📊 تصويت",
            description=desc,
            color=config.EMBED_COLOR
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.edit_message(embed=embed, view=self)


class AdvancedPoll(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._poll_counter = 0

    @app_commands.command(name="poll-advanced", description="📊 إنشاء تصويت بصري بأزرار وبار")
    @app_commands.describe(
        question="سؤال التصويت",
        options="الخيارات مفصولة بفاصلة (مثال: نعم,لا,ربما)"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def poll_advanced(self, interaction: discord.Interaction, question: str, options: str):
        opts = [o.strip() for o in options.split(",") if o.strip()]
        if len(opts) < 2:
            await interaction.response.send_message("❌ أدخل خيارين على الأقل مفصولين بفاصلة!", ephemeral=True)
            return
        if len(opts) > 9:
            await interaction.response.send_message("❌ الحد الأقصى 9 خيارات!", ephemeral=True)
            return

        self._poll_counter += 1
        poll_id = self._poll_counter

        active_polls[poll_id] = {
            "question": question,
            "options": opts,
            "votes": [0] * len(opts),
            "user_votes": {}
        }

        total = 0
        desc = f"**{question}**\n\n"
        for opt in opts:
            desc += f"**{opt}**\n{make_bar(0, 0)} — 0 صوت\n\n"
        desc += "📊 مجموع الأصوات: **0**"

        embed = discord.Embed(title="📊 تصويت", description=desc, color=config.EMBED_COLOR)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")

        view = PollView(opts, poll_id)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(AdvancedPoll(bot))
