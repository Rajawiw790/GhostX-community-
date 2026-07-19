import discord
from discord.ext import commands
from discord import app_commands
import config
import db

AUTO_REPLY_COLLECTION = "auto_reply_rules"

def load_rules() -> dict:
    return db.load(AUTO_REPLY_COLLECTION)

def save_rules(rules: dict):
    db.save(AUTO_REPLY_COLLECTION, rules)


class AutoReply(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rules: dict = load_rules()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        guild_id = str(message.guild.id) if message.guild else None
        if not guild_id:
            return

        guild_rules = self.rules.get(guild_id, {})
        channel_id = str(message.channel.id)

        for rule_id, rule in guild_rules.items():
            if rule.get("channel_id") and rule["channel_id"] != channel_id:
                continue

            trigger = rule.get("trigger", "").lower()
            match_type = rule.get("match", "contains")
            content = message.content.lower()

            matched = False
            if match_type == "exact" and content == trigger:
                matched = True
            elif match_type == "startswith" and content.startswith(trigger):
                matched = True
            elif match_type == "contains" and trigger in content:
                matched = True

            if matched:
                reply = rule.get("reply", "")
                if reply:
                    await message.channel.send(reply)

    @app_commands.command(name="autoreply-add", description="🤖 إضافة رد أوتوماتيك على رسالة معينة")
    @app_commands.describe(
        trigger="الكلمة أو الجملة اللي تشغل الرد",
        reply="الرد اللي يرسله البوت",
        channel="الروم (اتركه فارغ لكل الرومات)",
        match="نوع المطابقة: contains / exact / startswith"
    )
    @app_commands.choices(match=[
        app_commands.Choice(name="يحتوي على (contains)", value="contains"),
        app_commands.Choice(name="مطابق تماماً (exact)", value="exact"),
        app_commands.Choice(name="يبدأ بـ (startswith)", value="startswith"),
    ])
    @app_commands.default_permissions(manage_guild=True)
    async def autoreply_add(
        self,
        interaction: discord.Interaction,
        trigger: str,
        reply: str,
        channel: discord.TextChannel = None,
        match: str = "contains"
    ):
        guild_id = str(interaction.guild_id)
        if guild_id not in self.rules:
            self.rules[guild_id] = {}

        import time
        rule_id = str(int(time.time()))
        self.rules[guild_id][rule_id] = {
            "trigger": trigger.lower(),
            "reply": reply,
            "channel_id": str(channel.id) if channel else None,
            "match": match
        }
        save_rules(self.rules)

        embed = discord.Embed(title="✅ تم إضافة الرد الأوتوماتيك", color=config.SUCCESS_COLOR)
        embed.add_field(name="🔑 المشغّل", value=f"`{trigger}`", inline=True)
        embed.add_field(name="📝 الرد", value=reply[:200], inline=True)
        embed.add_field(name="📌 الروم", value=channel.mention if channel else "كل الرومات", inline=True)
        embed.add_field(name="🔍 نوع المطابقة", value=match, inline=True)
        embed.add_field(name="🆔 المعرف", value=f"`{rule_id}`", inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="autoreply-list", description="📋 قائمة الردود الأوتوماتيكية")
    @app_commands.default_permissions(manage_guild=True)
    async def autoreply_list(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        guild_rules = self.rules.get(guild_id, {})

        if not guild_rules:
            await interaction.response.send_message("❌ لا توجد ردود أوتوماتيكية!", ephemeral=True)
            return

        embed = discord.Embed(title="📋 الردود الأوتوماتيكية", color=config.EMBED_COLOR)
        for rule_id, rule in list(guild_rules.items())[:15]:
            ch = f"<#{rule['channel_id']}>" if rule.get("channel_id") else "كل الرومات"
            embed.add_field(
                name=f"`{rule_id}` — {rule['trigger'][:30]}",
                value=f"رد: {rule['reply'][:50]}\nروم: {ch} | نوع: {rule['match']}",
                inline=False
            )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="autoreply-remove", description="🗑️ حذف رد أوتوماتيك")
    @app_commands.describe(rule_id="معرف القاعدة (من /autoreply-list)")
    @app_commands.default_permissions(manage_guild=True)
    async def autoreply_remove(self, interaction: discord.Interaction, rule_id: str):
        guild_id = str(interaction.guild_id)
        guild_rules = self.rules.get(guild_id, {})

        if rule_id not in guild_rules:
            await interaction.response.send_message("❌ معرف غير موجود!", ephemeral=True)
            return

        del self.rules[guild_id][rule_id]
        save_rules(self.rules)

        embed = discord.Embed(title="🗑️ تم الحذف", description=f"تم حذف القاعدة `{rule_id}`", color=config.ERROR_COLOR)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(AutoReply(bot))
