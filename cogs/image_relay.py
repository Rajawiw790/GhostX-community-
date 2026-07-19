import discord
from discord.ext import commands
from discord import app_commands
import config
import db

IMAGE_RELAY_COLLECTION = "image_relay_settings"

def load_settings() -> dict:
    return db.load(IMAGE_RELAY_COLLECTION)

def save_settings(settings: dict):
    db.save(IMAGE_RELAY_COLLECTION, settings)


class ImageRelay(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.settings: dict = load_settings()

    def _is_enabled(self, guild_id: str, channel_id: str) -> bool:
        guild = self.settings.get(guild_id, {})
        channels = guild.get("channels", [])
        return "all" in channels or channel_id in channels

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return
        if not message.attachments:
            return

        guild_id   = str(message.guild.id)
        channel_id = str(message.channel.id)

        if not self._is_enabled(guild_id, channel_id):
            return

        images = [a for a in message.attachments if a.content_type and a.content_type.startswith("image/")]
        if not images:
            return

        try:
            await message.delete()
        except Exception:
            pass

        for img in images:
            await message.channel.send(
                content=f"📸 **{message.author.display_name}**\n{img.url}"
            )

    @app_commands.command(name="imagerelay-setup", description="🖼️ Enable/disable image relay (posts images as plain links)")
    @app_commands.describe(
        channel="The channel (leave blank to apply to all channels)",
        enable="Enable or disable"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def imagerelay_setup(
        self,
        interaction: discord.Interaction,
        enable: bool = True,
        channel: discord.TextChannel = None
    ):
        guild_id = str(interaction.guild_id)
        if guild_id not in self.settings:
            self.settings[guild_id] = {"channels": []}

        target = str(channel.id) if channel else "all"

        if enable:
            if target not in self.settings[guild_id]["channels"]:
                self.settings[guild_id]["channels"].append(target)
            status = "✅ Enabled"
            color  = config.SUCCESS_COLOR
        else:
            if target in self.settings[guild_id]["channels"]:
                self.settings[guild_id]["channels"].remove(target)
            status = "❌ Disabled"
            color  = config.ERROR_COLOR

        save_settings(self.settings)

        embed = discord.Embed(title=f"🖼️ Image Relay — {status}", color=color)
        embed.add_field(name="📌 Channel", value=channel.mention if channel else "All channels", inline=True)
        embed.add_field(name="📊 Status",  value="Enabled ✅" if enable else "Disabled ❌",       inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(ImageRelay(bot))
