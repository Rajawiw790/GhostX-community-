"""
Music System — Ghostx Community
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/play   — Play or queue a song (YouTube search or a direct link)
/skip   — Skip current song
/stop   — Stop & clear queue
/pause  — Pause playback
/resume — Resume playback
/queue  — Show current queue
/nowplaying — Show current song
/volume — Set volume (0-100)
/loop   — Toggle loop mode
/join   — Join your voice channel
/leave  — Leave voice channel

Runs on Lavalink via the `mafic` client (see /mnt or README for setup —
LAVALINK_HOST / LAVALINK_PORT / LAVALINK_PASSWORD / LAVALINK_SECURE in
config.py or the .env file). The node connection itself is opened once in
main.py's setup_hook; this cog only ever talks to it through
interaction.guild.voice_client (a mafic.Player once connected).
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import mafic
from collections import deque
from dataclasses import dataclass
from datetime import datetime


def _fmt(ms) -> str:
    if not ms:
        return "??:??"
    sec = int(ms / 1000)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


@dataclass
class QueueItem:
    track: "mafic.Track"
    requester_id: int


# ── Per-guild state (kept in the cog, not on the Player — mafic.Player has
#    no built-in queue, so we track it ourselves) ──────────────────────────

class GuildQueue:
    def __init__(self):
        self.queue: deque[QueueItem] = deque()
        self.current: QueueItem | None = None
        self.loop: bool = False
        self.volume: int = 100
        self.skip_requested: bool = False
        self.text_channel: discord.TextChannel | None = None


_queues: dict[int, GuildQueue] = {}


def get_queue(guild_id: int) -> GuildQueue:
    if guild_id not in _queues:
        _queues[guild_id] = GuildQueue()
    return _queues[guild_id]


# ── Music Cog ────────────────────────────────────────────────────────────────

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _ensure_voice(self, interaction: discord.Interaction) -> "mafic.Player | None":
        if not interaction.user.voice:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ كن في روم صوتي أولاً!", color=config.ERROR_COLOR),
            )
            return None
        vc_ch = interaction.user.voice.channel
        player: mafic.Player = interaction.guild.voice_client
        try:
            if player and player.channel and player.channel.id != vc_ch.id:
                await player.disconnect(force=True)
                player = None
            if not player:
                player = await vc_ch.connect(cls=mafic.Player, self_deaf=True)
        except Exception as e:
            # Most common cause here is no Lavalink node being connected yet
            # (see main.py's setup_hook) — surface both possibilities.
            await interaction.followup.send(
                embed=discord.Embed(
                    description=(
                        f"❌ ما قدرتش نتصل بالروم الصوتي: `{e}`\n"
                        "-# إلا كانت هاد المشكلة عاودة تصاوب، تأكد بلي Lavalink node خدامة."
                    ),
                    color=config.ERROR_COLOR,
                ),
            )
            return None
        return player

    async def _play_next(self, player: "mafic.Player", guild_id: int):
        """Advance the queue by one — called after /play (idle) and after
        every natural track end via on_track_end below."""
        gq = get_queue(guild_id)

        if gq.skip_requested:
            gq.skip_requested = False
        elif gq.loop and gq.current:
            await player.play(gq.current.track, volume=gq.volume)
            return

        if gq.queue:
            gq.current = gq.queue.popleft()
            await player.play(gq.current.track, volume=gq.volume)
        else:
            gq.current = None

    def _now_playing_embed(self, gq: GuildQueue, requester: str = None) -> discord.Embed:
        t = gq.current.track
        embed = discord.Embed(
            title="🎵 يشتغل الآن",
            description=f"**[{t.title}]({t.uri or ''})**",
            color=config.SUCCESS_COLOR,
        )
        embed.add_field(name="⏱️ المدة", value=_fmt(t.length), inline=True)
        embed.add_field(name="🔊 الصوت", value=f"{gq.volume}%", inline=True)
        embed.add_field(name="🔁 Loop", value="✅ مفعل" if gq.loop else "❌ موقوف", inline=True)
        if t.artwork_url:
            embed.set_thumbnail(url=t.artwork_url)
        embed.set_footer(text=f"{'طلبه: ' + requester + ' | ' if requester else ''}Dev: {config.DEVELOPER}")
        return embed

    # ── Lavalink events ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_track_end(self, event: "mafic.TrackEndEvent"):
        player = event.player
        guild = getattr(player, "guild", None)
        if not guild:
            return
        gq = get_queue(guild.id)
        await self._play_next(player, guild.id)
        if gq.current and gq.text_channel:
            try:
                await gq.text_channel.send(embed=self._now_playing_embed(gq))
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_node_ready(self, node: "mafic.Node"):
        print(f"✅ Lavalink node ready: {node.label}")

    @commands.Cog.listener()
    async def on_node_unavailable(self, node: "mafic.Node"):
        print(f"⚠️ Lavalink node unavailable: {node.label}")

    # ── /join ────────────────────────────────────────────────────────────────

    @app_commands.command(name="join", description="📥 دخول الروم الصوتي")
    async def join(self, interaction: discord.Interaction):
        await interaction.response.defer()
        player = await self._ensure_voice(interaction)
        if player:
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f"📥 دخلت **{interaction.user.voice.channel.name}**",
                    color=config.SUCCESS_COLOR,
                )
            )

    # ── /leave ───────────────────────────────────────────────────────────────

    @app_commands.command(name="leave", description="📤 خروج من الروم الصوتي وإيقاف الموسيقى")
    async def leave(self, interaction: discord.Interaction):
        player: mafic.Player = interaction.guild.voice_client
        if player:
            gq = get_queue(interaction.guild.id)
            gq.queue.clear()
            gq.current = None
            gq.loop = False
            await player.disconnect()
            await interaction.response.send_message(
                embed=discord.Embed(description="📤 تم الخروج وإيقاف الموسيقى.", color=config.EMBED_COLOR)
            )
        else:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ البوت مش في روم صوتي!", color=config.ERROR_COLOR),
                ephemeral=True,
            )

    # ── /play ────────────────────────────────────────────────────────────────

    @app_commands.command(name="play", description="🎵 تشغيل أو إضافة أغنية للقائمة")
    @app_commands.describe(query="اسم الأغنية أو رابط (يوتيوب، ساوندكلاود...)")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        player = await self._ensure_voice(interaction)
        if not player:
            return

        gq = get_queue(interaction.guild.id)
        gq.text_channel = interaction.channel

        try:
            results = await player.fetch_tracks(query)
        except Exception as e:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ خطأ في البحث",
                    description=f"`{str(e)[:300]}`",
                    color=config.ERROR_COLOR,
                )
            )
            return

        if not results:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ ما لقيتش نتائج.", color=config.ERROR_COLOR)
            )
            return

        is_playlist = isinstance(results, mafic.Playlist)
        new_tracks = results.tracks if is_playlist else [results[0]]
        if not new_tracks:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ ما لقيتش نتائج.", color=config.ERROR_COLOR)
            )
            return

        was_idle = gq.current is None
        for t in new_tracks:
            gq.queue.append(QueueItem(track=t, requester_id=interaction.user.id))

        if was_idle:
            await self._play_next(player, interaction.guild.id)
            embed = self._now_playing_embed(gq, requester=str(interaction.user))
        elif is_playlist:
            embed = discord.Embed(
                title="📋 أُضيفت القائمة",
                description=f"🎶 **{results.name}** — {len(new_tracks)} أغنية",
                color=config.EMBED_COLOR,
            )
            embed.set_footer(text=f"طلبه: {interaction.user} | Dev: {config.DEVELOPER}")
        else:
            t = new_tracks[0]
            embed = discord.Embed(
                title="📋 أُضيف للقائمة",
                description=f"**[{t.title}]({t.uri or ''})**",
                color=config.EMBED_COLOR,
            )
            embed.add_field(name="⏱️ المدة", value=_fmt(t.length), inline=True)
            embed.add_field(name="📋 موقعه في القائمة", value=f"#{len(gq.queue)}", inline=True)
            if t.artwork_url:
                embed.set_thumbnail(url=t.artwork_url)
            embed.set_footer(text=f"طلبه: {interaction.user} | Dev: {config.DEVELOPER}")

        await interaction.followup.send(embed=embed)

    # ── /skip ────────────────────────────────────────────────────────────────

    @app_commands.command(name="skip", description="⏭️ تخطي الأغنية الحالية")
    async def skip(self, interaction: discord.Interaction):
        player: mafic.Player = interaction.guild.voice_client
        gq = get_queue(interaction.guild.id)
        if not player or not gq.current:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ لا توجد أغنية تشتغل!", color=config.ERROR_COLOR),
                ephemeral=True,
            )
            return
        gq.skip_requested = True
        await player.stop()
        await interaction.response.send_message(
            embed=discord.Embed(description="⏭️ تم تخطي الأغنية.", color=config.SUCCESS_COLOR)
        )

    # ── /stop ────────────────────────────────────────────────────────────────

    @app_commands.command(name="stop", description="⏹️ إيقاف الموسيقى وتفريغ القائمة")
    async def stop(self, interaction: discord.Interaction):
        player: mafic.Player = interaction.guild.voice_client
        gq = get_queue(interaction.guild.id)
        gq.queue.clear()
        gq.current = None
        gq.loop = False
        if player and player.current:
            await player.stop()
        embed = discord.Embed(
            description="⏹️ توقفت الموسيقى وتم تفريغ القائمة.",
            color=config.ERROR_COLOR,
        )
        await interaction.response.send_message(embed=embed)

    # ── /pause ───────────────────────────────────────────────────────────────

    @app_commands.command(name="pause", description="⏸️ إيقاف مؤقت للموسيقى")
    async def pause(self, interaction: discord.Interaction):
        player: mafic.Player = interaction.guild.voice_client
        if player and player.current and not player.paused:
            await player.pause(True)
            await interaction.response.send_message(
                embed=discord.Embed(description="⏸️ تم الإيقاف المؤقت.", color=config.WARNING_COLOR)
            )
        else:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ لا توجد أغنية تشتغل!", color=config.ERROR_COLOR),
                ephemeral=True,
            )

    # ── /resume ──────────────────────────────────────────────────────────────

    @app_commands.command(name="resume", description="▶️ استئناف الموسيقى")
    async def resume(self, interaction: discord.Interaction):
        player: mafic.Player = interaction.guild.voice_client
        if player and player.paused:
            await player.resume()
            await interaction.response.send_message(
                embed=discord.Embed(description="▶️ تم استئناف الموسيقى.", color=config.SUCCESS_COLOR)
            )
        else:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ الموسيقى مش متوقفة!", color=config.ERROR_COLOR),
                ephemeral=True,
            )

    # ── /queue ───────────────────────────────────────────────────────────────

    @app_commands.command(name="queue", description="📋 عرض قائمة الأغاني")
    async def queue_cmd(self, interaction: discord.Interaction):
        gq = get_queue(interaction.guild.id)

        embed = discord.Embed(
            title="📋 قائمة الأغاني",
            color=config.EMBED_COLOR,
            timestamp=datetime.now(),
        )

        if gq.current:
            t = gq.current.track
            embed.add_field(
                name="🎵 يشتغل الآن",
                value=f"**[{t.title}]({t.uri or ''})** `{_fmt(t.length)}`",
                inline=False,
            )
        else:
            embed.add_field(name="🎵 يشتغل الآن", value="`لا توجد أغنية`", inline=False)

        if gq.queue:
            lines = []
            for i, item in enumerate(list(gq.queue)[:10], 1):
                t = item.track
                lines.append(f"`{i}.` **[{t.title}]({t.uri or ''})** `{_fmt(t.length)}`")
            if len(gq.queue) > 10:
                lines.append(f"*...و {len(gq.queue) - 10} أغاني أخرى*")
            embed.add_field(name="📋 القائمة", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="📋 القائمة", value="`القائمة فارغة`", inline=False)

        embed.add_field(name="🔁 Loop", value="✅ مفعل" if gq.loop else "❌ موقوف", inline=True)
        embed.add_field(name="🔊 الصوت", value=f"{gq.volume}%", inline=True)
        embed.add_field(name="📊 إجمالي القائمة", value=f"{len(gq.queue)} أغاني", inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

    # ── /nowplaying ───────────────────────────────────────────────────────────

    @app_commands.command(name="nowplaying", description="🎵 معلومات الأغنية الحالية")
    async def nowplaying(self, interaction: discord.Interaction):
        gq = get_queue(interaction.guild.id)
        if not gq.current:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ لا توجد أغنية تشتغل!", color=config.ERROR_COLOR),
                ephemeral=True,
            )
            return
        embed = self._now_playing_embed(gq)
        embed.timestamp = datetime.now()
        embed.add_field(name="📋 في القائمة", value=f"{len(gq.queue)} أغاني قادمة", inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /volume ───────────────────────────────────────────────────────────────

    @app_commands.command(name="volume", description="🔊 ضبط مستوى الصوت (0-100)")
    @app_commands.describe(level="مستوى الصوت من 0 إلى 100")
    async def volume(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 100]):
        gq = get_queue(interaction.guild.id)
        gq.volume = level
        player: mafic.Player = interaction.guild.voice_client
        if player and player.connected:
            await player.set_volume(level)
        embed = discord.Embed(
            description=f"🔊 تم ضبط الصوت على **{level}%**",
            color=config.SUCCESS_COLOR,
        )
        await interaction.response.send_message(embed=embed)

    # ── /loop ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="loop", description="🔁 تفعيل/إيقاف تكرار الأغنية")
    async def loop(self, interaction: discord.Interaction):
        gq = get_queue(interaction.guild.id)
        gq.loop = not gq.loop
        state = "✅ مفعل" if gq.loop else "❌ موقوف"
        embed = discord.Embed(
            description=f"🔁 التكرار: **{state}**",
            color=config.SUCCESS_COLOR if gq.loop else config.ERROR_COLOR,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
