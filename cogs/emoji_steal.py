"""
Emoji Stealer — Ghostx Community
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/emoji steal <emoji>              — copy one emoji from any server to this server
/emoji stealall <server_id>       — copy ALL emojis from another server the bot is in
/emoji list <server_id>           — list emojis available in another server (bot must be there)
/emoji delete <name>              — delete an emoji from this server by name
/emoji uploadzip <zip_file>       — upload a .zip of images and add them all as emojis
"""

import io
import re
import os
import asyncio
import zipfile
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

import config


class EmojiGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(
            name="emoji",
            description="😄 Emoji tools",
            default_permissions=discord.Permissions(manage_emojis=True),
        )
        self.bot = bot

    # ─── helper: download image bytes ────────────────────────────────────────
    async def _fetch_bytes(self, url: str) -> bytes | None:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        return await r.read()
        except Exception:
            pass
        return None

    # ─── /emoji steal <emoji> ─────────────────────────────────────────────────
    @app_commands.command(name="steal", description="😄 Copy one emoji to this server")
    @app_commands.describe(emoji="The emoji you want to steal (paste it directly)")
    async def steal(self, interaction: discord.Interaction, emoji: str):
        await interaction.response.defer(ephemeral=True)

        # Try to parse as a custom emoji  <:name:id>  or  <a:name:id>
        import re
        match = re.match(r"<a?:(\w+):(\d+)>", emoji.strip())
        if not match:
            await interaction.followup.send(
                "❌ That's not a custom emoji. Paste a custom emoji like `<:name:id>` or `<a:name:id>`.",
                ephemeral=True,
            )
            return

        name, eid = match.group(1), int(match.group(2))
        animated  = emoji.strip().startswith("<a:")
        ext       = "gif" if animated else "png"
        url       = f"https://cdn.discordapp.com/emojis/{eid}.{ext}?size=128&quality=lossless"

        data = await self._fetch_bytes(url)
        if not data:
            await interaction.followup.send("❌ Couldn't download the emoji image.", ephemeral=True)
            return

        try:
            new_emoji = await interaction.guild.create_custom_emoji(
                name=name, image=data,
                reason=f"Stolen by {interaction.user} via /emoji steal"
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Missing **Manage Emojis** permission.", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Failed: `{e}`", ephemeral=True)
            return

        embed = discord.Embed(
            title="✅ Emoji Stolen!",
            description=f"{new_emoji} `:{new_emoji.name}:` added to **{interaction.guild.name}**",
            color=config.SUCCESS_COLOR,
            timestamp=datetime.now(),
        )
        embed.set_thumbnail(url=new_emoji.url)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─── /emoji stealall <server_id> ─────────────────────────────────────────
    @app_commands.command(name="stealall", description="📦 Copy ALL emojis from another server the bot is in")
    @app_commands.describe(server_id="The ID of the source server")
    async def stealall(self, interaction: discord.Interaction, server_id: str):
        await interaction.response.defer(ephemeral=True)

        try:
            gid = int(server_id.strip())
        except ValueError:
            await interaction.followup.send("❌ Invalid server ID.", ephemeral=True)
            return

        source = self.bot.get_guild(gid)
        if not source:
            await interaction.followup.send(
                "❌ I'm not in that server, or the ID is wrong.\n"
                "The bot must be in **both** servers.",
                ephemeral=True,
            )
            return

        if not source.emojis:
            await interaction.followup.send(f"❌ **{source.name}** has no custom emojis.", ephemeral=True)
            return

        target = interaction.guild
        # Check remaining emoji slots
        normal_limit = target.emoji_limit
        normal_used  = sum(1 for e in target.emojis if not e.animated)
        anim_used    = sum(1 for e in target.emojis if e.animated)
        normal_free  = normal_limit - normal_used
        anim_free    = normal_limit - anim_used

        to_copy = source.emojis
        skipped, copied, failed = [], [], []

        status_embed = discord.Embed(
            title=f"📦 Copying emojis from **{source.name}**…",
            description=f"Found **{len(to_copy)}** emojis. Starting…",
            color=config.WARNING_COLOR,
        )
        status_msg = await interaction.followup.send(embed=status_embed, ephemeral=True)

        for i, em in enumerate(to_copy):
            # Slot check
            if em.animated and anim_free <= 0:
                skipped.append(em.name); continue
            if not em.animated and normal_free <= 0:
                skipped.append(em.name); continue

            data = await self._fetch_bytes(str(em.url))
            if not data:
                failed.append(em.name); continue

            # Avoid duplicate names
            existing_names = {e.name.lower() for e in target.emojis}
            final_name = em.name
            if final_name.lower() in existing_names:
                final_name = f"{em.name}_copy"
            if final_name.lower() in existing_names:
                skipped.append(em.name); continue

            try:
                new = await target.create_custom_emoji(
                    name=final_name, image=data,
                    reason=f"EmojiSteal from {source.name} by {interaction.user}"
                )
                copied.append(str(new))
                if em.animated: anim_free -= 1
                else:           normal_free -= 1
            except discord.HTTPException:
                failed.append(em.name)

            # Update status every 5 emojis
            if (i + 1) % 5 == 0:
                status_embed.description = (
                    f"Progress: **{i+1}/{len(to_copy)}**\n"
                    f"✅ Copied: {len(copied)} | ❌ Failed: {len(failed)} | ⏭️ Skipped: {len(skipped)}"
                )
                try:
                    await status_msg.edit(embed=status_embed)
                except Exception:
                    pass
            await asyncio.sleep(0.6)   # rate-limit friendly

        # Final report
        result = discord.Embed(
            title="✅ Emoji Copy Complete!",
            color=config.SUCCESS_COLOR,
            timestamp=datetime.now(),
        )
        result.add_field(name="✅ Copied",  value=str(len(copied)),  inline=True)
        result.add_field(name="❌ Failed",  value=str(len(failed)),  inline=True)
        result.add_field(name="⏭️ Skipped", value=str(len(skipped)), inline=True)
        result.add_field(name="📤 Source",  value=f"**{source.name}**", inline=False)
        if failed:
            result.add_field(name="Failed names", value=", ".join(failed[:20]), inline=False)
        if skipped:
            result.add_field(name="Skipped (no slots / duplicate)", value=", ".join(skipped[:20]), inline=False)
        result.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await status_msg.edit(embed=result)

    # ─── /emoji list <server_id> ──────────────────────────────────────────────
    @app_commands.command(name="list", description="📋 List emojis in another server the bot is in")
    @app_commands.describe(server_id="The ID of the server to list emojis from")
    async def list_emojis(self, interaction: discord.Interaction, server_id: str):
        await interaction.response.defer(ephemeral=True)

        try:
            gid = int(server_id.strip())
        except ValueError:
            await interaction.followup.send("❌ Invalid server ID.", ephemeral=True)
            return

        source = self.bot.get_guild(gid)
        if not source:
            await interaction.followup.send("❌ Bot is not in that server.", ephemeral=True)
            return

        if not source.emojis:
            await interaction.followup.send(f"❌ **{source.name}** has no custom emojis.", ephemeral=True)
            return

        normal = [e for e in source.emojis if not e.animated]
        anim   = [e for e in source.emojis if e.animated]

        embed = discord.Embed(
            title=f"😄 Emojis in {source.name}",
            color=config.EMBED_COLOR,
            timestamp=datetime.now(),
        )
        embed.set_thumbnail(url=source.icon.url if source.icon else None)

        if normal:
            chunks = [normal[i:i+20] for i in range(0, len(normal), 20)]
            for chunk in chunks[:3]:
                embed.add_field(
                    name=f"🖼️ Static ({len(normal)})",
                    value=" ".join(str(e) for e in chunk),
                    inline=False,
                )
        if anim:
            chunks = [anim[i:i+20] for i in range(0, len(anim), 20)]
            for chunk in chunks[:3]:
                embed.add_field(
                    name=f"🎞️ Animated ({len(anim)})",
                    value=" ".join(str(e) for e in chunk),
                    inline=False,
                )

        embed.set_footer(text=f"Total: {len(source.emojis)} | Use /emoji stealall {source.id} to copy all")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─── /emoji delete <name> ────────────────────────────────────────────────
    @app_commands.command(name="delete", description="🗑️ Delete an emoji from this server by name")
    @app_commands.describe(name="The emoji name (without colons)")
    async def delete_emoji(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)

        target = discord.utils.get(interaction.guild.emojis, name=name)
        if not target:
            await interaction.followup.send(f"❌ No emoji named `:{name}:` found.", ephemeral=True)
            return
        try:
            await target.delete(reason=f"Deleted by {interaction.user} via /emoji delete")
        except discord.Forbidden:
            await interaction.followup.send("❌ Missing permission to delete emojis.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🗑️ Emoji Deleted",
            description=f"Emoji `:{name}:` removed from **{interaction.guild.name}**.",
            color=config.ERROR_COLOR,
        )
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─── /emoji uploadzip <zip_file> ─────────────────────────────────────────
    @app_commands.command(name="uploadzip", description="📦 Upload a ZIP of images and add them all as emojis")
    @app_commands.describe(zip_file="A .zip file containing PNG/JPG/GIF images named after the emoji")
    async def uploadzip(self, interaction: discord.Interaction, zip_file: discord.Attachment):
        await interaction.response.defer(ephemeral=True)

        # Validate file type
        if not zip_file.filename.lower().endswith('.zip'):
            await interaction.followup.send("❌ الرجاء إرسال ملف **ZIP** فقط.", ephemeral=True)
            return

        if zip_file.size > 8 * 1024 * 1024:  # 8 MB limit
            await interaction.followup.send("❌ الملف كبير جداً (الحد الأقصى 8MB).", ephemeral=True)
            return

        # Download zip
        zip_bytes = await self._fetch_bytes(zip_file.url)
        if not zip_bytes:
            await interaction.followup.send("❌ تعذّر تحميل الملف.", ephemeral=True)
            return

        target = interaction.guild
        normal_limit = target.emoji_limit
        normal_used  = sum(1 for e in target.emojis if not e.animated)
        anim_used    = sum(1 for e in target.emojis if e.animated)
        normal_free  = normal_limit - normal_used
        anim_free    = normal_limit - anim_used

        VALID_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}

        copied, failed, skipped = [], [], []

        status_embed = discord.Embed(
            title="📦 جاري رفع الإيموجيات من الـ ZIP…",
            description="يتم المعالجة...",
            color=config.WARNING_COLOR,
        )
        status_msg = await interaction.followup.send(embed=status_embed, ephemeral=True)

        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                entries = [
                    name for name in zf.namelist()
                    if os.path.splitext(name.lower())[1] in VALID_EXT
                    and not name.startswith('__MACOSX')
                    and not os.path.basename(name).startswith('.')
                ]

                if not entries:
                    await status_msg.edit(
                        embed=discord.Embed(
                            description="❌ لم يتم العثور على صور صالحة داخل الـ ZIP.\nتأكد أن الملفات بصيغة PNG/JPG/GIF/WEBP.",
                            color=config.ERROR_COLOR,
                        )
                    )
                    return

                for i, entry in enumerate(entries):
                    basename = os.path.basename(entry)
                    stem, ext = os.path.splitext(basename)
                    animated  = ext.lower() == '.gif'

                    # Clean name — only alphanumeric + underscore, max 32 chars
                    clean = re.sub(r'[^a-zA-Z0-9_]', '_', stem)[:32].strip('_') or f"emoji_{i}"

                    # Slot check
                    if animated and anim_free <= 0:
                        skipped.append(clean); continue
                    if not animated and normal_free <= 0:
                        skipped.append(clean); continue

                    # Deduplicate names
                    existing_names = {e.name.lower() for e in target.emojis}
                    final_name = clean
                    if final_name.lower() in existing_names:
                        final_name = f"{clean}_2"
                    if final_name.lower() in existing_names:
                        skipped.append(clean); continue

                    try:
                        img_data = zf.read(entry)
                        new_emoji = await target.create_custom_emoji(
                            name=final_name,
                            image=img_data,
                            reason=f"ZIP upload by {interaction.user}",
                        )
                        copied.append(str(new_emoji))
                        if animated: anim_free -= 1
                        else:        normal_free -= 1
                    except discord.HTTPException as e:
                        failed.append(f"{clean} ({e.text[:40]})")
                    except Exception as e:
                        failed.append(f"{clean} ({str(e)[:40]})")

                    # Update every 5
                    if (i + 1) % 5 == 0:
                        status_embed.description = (
                            f"Progress: **{i+1}/{len(entries)}**\n"
                            f"✅ {len(copied)} | ❌ {len(failed)} | ⏭️ {len(skipped)}"
                        )
                        try:
                            await status_msg.edit(embed=status_embed)
                        except Exception:
                            pass

                    await asyncio.sleep(0.5)

        except zipfile.BadZipFile:
            await status_msg.edit(
                embed=discord.Embed(description="❌ ملف ZIP تالف أو غير صالح.", color=config.ERROR_COLOR)
            )
            return

        # Final report
        result = discord.Embed(
            title="✅ رفع الإيموجيات من ZIP — اكتمل",
            color=config.SUCCESS_COLOR,
            timestamp=datetime.now(),
        )
        result.add_field(name="✅ تم الرفع",  value=str(len(copied)),  inline=True)
        result.add_field(name="❌ فشل",       value=str(len(failed)),  inline=True)
        result.add_field(name="⏭️ تم تخطيه", value=str(len(skipped)), inline=True)
        if copied:
            preview = " ".join(copied[:20])
            result.add_field(name="الإيموجيات المضافة", value=preview[:1000], inline=False)
        if failed:
            result.add_field(name="الفاشلة", value="\n".join(failed[:10])[:500], inline=False)
        result.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await status_msg.edit(embed=result)


class EmojiSteal(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._group = EmojiGroup(bot)
        bot.tree.add_command(self._group)

    async def cog_unload(self):
        self.bot.tree.remove_command("emoji")


async def setup(bot: commands.Bot):
    await bot.add_cog(EmojiSteal(bot))
