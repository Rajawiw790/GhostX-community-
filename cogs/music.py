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
/panel  — 🎛️ Open a full interactive control panel (buttons)

Runs on Lavalink via the `wavelink` client (see LAVALINK_SETUP.md for setup —
LAVALINK_HOST / LAVALINK_PORT / LAVALINK_PASSWORD / LAVALINK_SECURE in
config.py or the .env file). The node connection itself is opened once in
main.py's setup_hook; this cog only ever talks to it through
interaction.guild.voice_client (a wavelink.Player once connected).
"""

import discord
from discord.ext import commands
from discord import app_commands
import config
import wavelink
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
    track: "wavelink.Playable"
    requester_id: int


# ── Per-guild state (kept in the cog, not on the Player — we track our own
#    queue/loop/volume so /queue, /loop, /nowplaying stay simple) ──────────

class GuildQueue:
    def __init__(self):
        self.queue: deque[QueueItem] = deque()
        self.current: QueueItem | None = None
        self.loop: bool = False
        self.volume: int = 100
        self.skip_requested: bool = False
        self.text_channel: discord.TextChannel | None = None
        # Live control-panel message, kept in sync on every track change
        self.panel_message: discord.Message | None = None


_queues: dict[int, GuildQueue] = {}


def get_queue(guild_id: int) -> GuildQueue:
    if guild_id not in _queues:
        _queues[guild_id] = GuildQueue()
    return _queues[guild_id]


# ── Control Panel (persistent view — works across bot restarts) ────────────

class MusicControlView(discord.ui.View):
    def __init__(self, cog: "Music"):
        super().__init__(timeout=None)
        self.cog = cog

    async def _refresh_message(self, interaction: discord.Interaction):
        gq = get_queue(interaction.guild.id)
        embed = self.cog._panel_embed(gq)
        try:
            await interaction.message.edit(embed=embed, view=self)
        except Exception:
            pass

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, custom_id="music_panel_pauseresume")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        player: wavelink.Player = interaction.guild.voice_client
        if not player or not player.playing:
            await interaction.response.send_message("❌ لا توجد أغنية تشتغل!", ephemeral=True)
            return
        await player.pause(not player.paused)
        await interaction.response.defer()
        await self._refresh_message(interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="music_panel_skip")
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        player: wavelink.Player = interaction.guild.voice_client
        gq = get_queue(interaction.guild.id)
        if not player or not gq.current:
            await interaction.response.send_message("❌ لا توجد أغنية تشتغل!", ephemeral=True)
            return
        gq.skip_requested = True
        await player.stop()  # triggers on_wavelink_track_end -> advances queue
        await interaction.response.defer()

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="music_panel_stop")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        player: wavelink.Player = interaction.guild.voice_client
        gq = get_queue(interaction.guild.id)
        gq.queue.clear()
        gq.current = None
        gq.loop = False
        if player and player.playing:
            await player.stop()
        await interaction.response.defer()
        await self._refresh_message(interaction)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="music_panel_loop")
    async def loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        gq = get_queue(interaction.guild.id)
        gq.loop = not gq.loop
        await interaction.response.defer()
        await self._refresh_message(interaction)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, custom_id="music_panel_voldown")
    async def vol_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        player: wavelink.Player = interaction.guild.voice_client
        gq = get_queue(interaction.guild.id)
        gq.volume = max(0, gq.volume - 10)
        if player and player.connected:
            await player.set_volume(gq.volume)
        await interaction.response.defer()
        await self._refresh_message(interaction)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, custom_id="music_panel_volup")
    async def vol_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        player: wavelink.Player = interaction.guild.voice_client
        gq = get_queue(interaction.guild.id)
        gq.volume = min(100, gq.volume + 10)
        if player and player.connected:
            await player.set_volume(gq.volume)
        await interaction.response.defer()
        await self._refresh_message(interaction)

    @discord.ui.button(emoji="📋", style=discord.ButtonStyle.secondary, custom_id="music_panel_queuelist", row=1)
    async def queue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        gq = get_queue(interaction.guild.id)
        if not gq.queue:
            await interaction.response.send_message("📋 القائمة فارغة حاليا.", ephemeral=True)
            return
        lines = []
        for i, item in enumerate(list(gq.queue)[:15], 1):
            t = item.track
            lines.append(f"`{i}.` **{t.title}** `{_fmt(t.length)}`")
        if len(gq.queue) > 15:
            lines.append(f"*...و {len(gq.queue) - 15} أخرى*")
        embed = discord.Embed(title="📋 القائمة الكاملة", description="\n".join(lines), color=config.EMBED_COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(emoji="👋", style=discord.ButtonStyle.danger, custom_id="music_panel_leave", row=1)
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        player: wavelink.Player = interaction.guild.voice_client
        gq = get_queue(interaction.guild.id)
        if not player:
            await interaction.response.send_message("❌ البوت مش في روم صوتي!", ephemeral=True)
            return
        gq.queue.clear()
        gq.current = None
        gq.loop = False
        gq.panel_message = None
        await player.disconnect()
        await interaction.response.defer()
        try:
            await interaction.message.edit(
                embed=discord.Embed(description="📤 تم الخروج وإيقاف الموسيقى.", color=config.ERROR_COLOR),
                view=None,
            )
        except Exception:
            pass


# ── Music Cog ────────────────────────────────────────────────────────────────

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _ensure_voice(self, interaction: discord.Interaction) -> "wavelink.Player | None":
        if not interaction.user.voice:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ كن في روم صوتي أولاً!", color=config.ERROR_COLOR),
            )
            return None
        vc_ch = interaction.user.voice.channel
        player: wavelink.Player = interaction.guild.voice_client
        try:
            if player and player.channel and player.channel.id != vc_ch.id:
                await player.disconnect(force=True)
                player = None
            if not player:
                player = await vc_ch.connect(cls=wavelink.Player, self_deaf=True)
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

    async def _play_next(self, player: "wavelink.Player", guild_id: int):
        """Advance the queue by one — called after /play (idle) and after
        every natural track end via on_wavelink_track_end below."""
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
        if t.artwork:
            embed.set_thumbnail(url=t.artwork)
        embed.set_footer(text=f"{'طلبه: ' + requester + ' | ' if requester else ''}Dev: {config.DEVELOPER}")
        return embed

    def _panel_embed(self, gq: GuildQueue) -> discord.Embed:
        if gq.current:
            t = gq.current.track
            embed = discord.Embed(
                title="🎛️ لوحة تحكم الموسيقى",
                description=f"**يشتغل الآن:**\n**[{t.title}]({t.uri or ''})**",
                color=config.SUCCESS_COLOR,
            )
            embed.add_field(name="⏱️ المدة", value=_fmt(t.length), inline=True)
            if t.artwork:
                embed.set_thumbnail(url=t.artwork)
        else:
            embed = discord.Embed(
                title="🎛️ لوحة تحكم الموسيقى",
                description="`لا توجد أغنية تشتغل حاليا`",
                color=config.EMBED_COLOR,
            )

        embed.add_field(name="🔊 الصوت", value=f"{gq.volume}%", inline=True)
        embed.add_field(name="🔁 Loop", value="✅" if gq.loop else "❌", inline=True)

        if gq.queue:
            lines = []
            for i, item in enumerate(list(gq.queue)[:5], 1):
                t2 = item.track
                lines.append(f"`{i}.` {t2.title}")
            if len(gq.queue) > 5:
                lines.append(f"*...و {len(gq.queue) - 5} أخرى*")
            embed.add_field(name=f"📋 القائمة ({len(gq.queue)})", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="📋 القائمة", value="`فارغة`", inline=False)

        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        return embed

    async def _refresh_panel(self, gq: GuildQueue):
        if gq.panel_message:
            try:
                await gq.panel_message.edit(embed=self._panel_embed(gq))
            except Exception:
                pass

    # ── Lavalink events ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: "wavelink.TrackEndEventPayload"):
        player = payload.player
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
        await self._refresh_panel(gq)

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: "wavelink.NodeReadyEventPayload"):
        print(f"✅ Lavalink node ready: {payload.node!r} (session_id={payload.node.session_id})")

    @commands.Cog.listener()
    async def on_wavelink_node_disconnected(self, payload: "wavelink.NodeDisconnectedEventPayload"):
        print(f"⚠️ Lavalink node disconnected: {payload.node!r}")

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
        player: wavelink.Player = interaction.guild.voice_client
        if player:
            gq = get_queue(interaction.guild.id)
            gq.queue.clear()
            gq.current = None
            gq.loop = False
            gq.panel_message = None
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
            results: wavelink.Search = await wavelink.Playable.search(query)
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

        is_playlist = isinstance(results, wavelink.Playlist)
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
            if t.artwork:
                embed.set_thumbnail(url=t.artwork)
            embed.set_footer(text=f"طلبه: {interaction.user} | Dev: {config.DEVELOPER}")

        await interaction.followup.send(embed=embed)
        await self._refresh_panel(gq)

    # ── /skip ────────────────────────────────────────────────────────────────

    @app_commands.command(name="skip", description="⏭️ تخطي الأغنية الحالية")
    async def skip(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client
        gq = get_queue(interaction.guild.id)
        if not player or not gq.current:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ لا توجد أغنية تشتغل!", color=config.ERROR_COLOR),
                ephemeral=True,
            )
            return
        gq.skip_requested = True
        # NOTE: wavelink.Player has no `.skip()` method — this was the bug.
        # Stopping the current track fires on_wavelink_track_end, which
        # advances the queue for us.
        await player.stop()
        await interaction.response.send_message(
            embed=discord.Embed(description="⏭️ تم تخطي الأغنية.", color=config.SUCCESS_COLOR)
        )

    # ── /stop ────────────────────────────────────────────────────────────────

    @app_commands.command(name="stop", description="⏹️ إيقاف الموسيقى وتفريغ القائمة")
    async def stop(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client
        gq = get_queue(interaction.guild.id)
        gq.queue.clear()
        gq.current = None
        gq.loop = False
        if player and player.playing:
            await player.stop()
        embed = discord.Embed(
            description="⏹️ توقفت الموسيقى وتم تفريغ القائمة.",
            color=config.ERROR_COLOR,
        )
        await interaction.response.send_message(embed=embed)
        await self._refresh_panel(gq)

    # ── /pause ───────────────────────────────────────────────────────────────

    @app_commands.command(name="pause", description="⏸️ إيقاف مؤقت للموسيقى")
    async def pause(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client
        if player and player.playing and not player.paused:
            await player.pause(True)
            await interaction.response.send_message(
                embed=discord.Embed(description="⏸️ تم الإيقاف المؤقت.", color=config.WARNING_COLOR)
            )
            await self._refresh_panel(get_queue(interaction.guild.id))
        else:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ لا توجد أغنية تشتغل!", color=config.ERROR_COLOR),
                ephemeral=True,
            )

    # ── /resume ──────────────────────────────────────────────────────────────

    @app_commands.command(name="resume", description="▶️ استئناف الموسيقى")
    async def resume(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client
        if player and player.paused:
            await player.pause(False)
            await interaction.response.send_message(
                embed=discord.Embed(description="▶️ تم استئناف الموسيقى.", color=config.SUCCESS_COLOR)
            )
            await self._refresh_panel(get_queue(interaction.guild.id))
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
        player: wavelink.Player = interaction.guild.voice_client
        if player and player.connected:
            await player.set_volume(level)
        embed = discord.Embed(
            description=f"🔊 تم ضبط الصوت على **{level}%**",
            color=config.SUCCESS_COLOR,
        )
        await interaction.response.send_message(embed=embed)
        await self._refresh_panel(gq)

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
        await self._refresh_panel(gq)

    # ── /panel ────────────────────────────────────────────────────────────────

    @app_commands.command(name="panel", description="🎛️ فتح لوحة تحكم كاملة للموسيقى (أزرار)")
    async def panel(self, interaction: discord.Interaction):
        gq = get_queue(interaction.guild.id)
        embed = self._panel_embed(gq)
        view = MusicControlView(self)
        await interaction.response.send_message(embed=embed, view=view)
        gq.panel_message = await interaction.original_response()


async def setup(bot: commands.Bot):
    cog = Music(bot)
    await bot.add_cog(cog)
    # Register the view as persistent so buttons keep working after a restart
    bot.add_view(MusicControlView(cog))
