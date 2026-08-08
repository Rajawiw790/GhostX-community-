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
            await interaction.response.send_message("❌ No song is playing!", ephemeral=True)
            return
        await player.pause(not player.paused)
        await interaction.response.defer()
        await self._refresh_message(interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="music_panel_skip")
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        player: wavelink.Player = interaction.guild.voice_client
        gq = get_queue(interaction.guild.id)
        if not player or not gq.current:
            await interaction.response.send_message("❌ No song is playing!", ephemeral=True)
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
            await interaction.response.send_message("📋 Queue is empty right now.", ephemeral=True)
            return
        lines = []
        for i, item in enumerate(list(gq.queue)[:15], 1):
            t = item.track
            lines.append(f"`{i}.` **{t.title}** `{_fmt(t.length)}`")
        if len(gq.queue) > 15:
            lines.append(f"*...and {len(gq.queue) - 15} more*")
        embed = discord.Embed(title="📋 Full Queue", description="\n".join(lines), color=config.EMBED_COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(emoji="👋", style=discord.ButtonStyle.danger, custom_id="music_panel_leave", row=1)
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        player: wavelink.Player = interaction.guild.voice_client
        gq = get_queue(interaction.guild.id)
        if not player:
            await interaction.response.send_message("❌ Bot mkhynch f voice!", ephemeral=True)
            return
        gq.queue.clear()
        gq.current = None
        gq.loop = False
        gq.panel_message = None
        await player.disconnect()
        await interaction.response.defer()
        try:
            await interaction.message.edit(
                embed=discord.Embed(description="📤 Left the room and stopped the music.", color=config.ERROR_COLOR),
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
                embed=discord.Embed(description="❌ Khask tkon f voice channel!", color=config.ERROR_COLOR),
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
                        f"❌ Error voice: `{e}`\n"
                        "-# Try again in a moment, or check that Lavalink is connected."
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
            title="🎵 Now Playing",
            description=f"**[{t.title}]({t.uri or ''})**",
            color=config.SUCCESS_COLOR,
        )
        embed.add_field(name="⏱️ Duration", value=_fmt(t.length), inline=True)
        embed.add_field(name="🔊 Volume", value=f"{gq.volume}%", inline=True)
        embed.add_field(name="🔁 Loop", value="✅ On" if gq.loop else "❌ Off", inline=True)
        if t.artwork:
            embed.set_thumbnail(url=t.artwork)
        embed.set_footer(text=f"{'Requested by: ' + requester + ' | ' if requester else ''}Dev: {config.DEVELOPER}")
        return embed

    def _panel_embed(self, gq: GuildQueue) -> discord.Embed:
        if gq.current:
            t = gq.current.track
            embed = discord.Embed(
                title="🎛️ Music Control Panel",
                description=f"**Now playing:**\n**[{t.title}]({t.uri or ''})**",
                color=config.SUCCESS_COLOR,
            )
            embed.add_field(name="⏱️ Duration", value=_fmt(t.length), inline=True)
            if t.artwork:
                embed.set_thumbnail(url=t.artwork)
        else:
            embed = discord.Embed(
                title="🎛️ Music Control Panel",
                description="`No song is playing right now`",
                color=config.EMBED_COLOR,
            )

        embed.add_field(name="🔊 Volume", value=f"{gq.volume}%", inline=True)
        embed.add_field(name="🔁 Loop", value="✅" if gq.loop else "❌", inline=True)

        if gq.queue:
            lines = []
            for i, item in enumerate(list(gq.queue)[:5], 1):
                t2 = item.track
                lines.append(f"`{i}.` {t2.title}")
            if len(gq.queue) > 5:
                lines.append(f"*...and {len(gq.queue) - 5} more*")
            embed.add_field(name=f"📋 Queue ({len(gq.queue)})", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="📋 Queue", value="`Empty`", inline=False)

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

    @app_commands.command(name="join", description="📥 Join the voice channel")
    async def join(self, interaction: discord.Interaction):
        await interaction.response.defer()
        player = await self._ensure_voice(interaction)
        if player:
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f"📥 Joined **{interaction.user.voice.channel.name}**",
                    color=config.SUCCESS_COLOR,
                )
            )

    # ── /leave ───────────────────────────────────────────────────────────────

    @app_commands.command(name="leave", description="📤 Leave the voice channel and stop the music")
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
                embed=discord.Embed(description="📤 Left the room and stopped the music.", color=config.EMBED_COLOR)
            )
        else:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Bot mashi f voice channel!", color=config.ERROR_COLOR),
                ephemeral=True,
            )

    # ── /play ────────────────────────────────────────────────────────────────

    @app_commands.command(name="play", description="🎵 Play or add a song to the queue")
    @app_commands.describe(query="Song name or a link (YouTube, SoundCloud...)")
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
                    title="❌ Search error",
                    description=f"`{str(e)[:300]}`",
                    color=config.ERROR_COLOR,
                )
            )
            return

        if not results:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ No results found.", color=config.ERROR_COLOR)
            )
            return

        is_playlist = isinstance(results, wavelink.Playlist)
        new_tracks = results.tracks if is_playlist else [results[0]]
        if not new_tracks:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ No results found.", color=config.ERROR_COLOR)
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
                title="📋 Playlist added",
                description=f"🎶 **{results.name}** — {len(new_tracks)} songs",
                color=config.EMBED_COLOR,
            )
            embed.set_footer(text=f"Requested by: {interaction.user} | Dev: {config.DEVELOPER}")
        else:
            t = new_tracks[0]
            embed = discord.Embed(
                title="📋 Added to queue",
                description=f"**[{t.title}]({t.uri or ''})**",
                color=config.EMBED_COLOR,
            )
            embed.add_field(name="⏱️ Duration", value=_fmt(t.length), inline=True)
            embed.add_field(name="📋 Position in queue", value=f"#{len(gq.queue)}", inline=True)
            if t.artwork:
                embed.set_thumbnail(url=t.artwork)
            embed.set_footer(text=f"Requested by: {interaction.user} | Dev: {config.DEVELOPER}")

        await interaction.followup.send(embed=embed)
        await self._refresh_panel(gq)

    # ── /skip ────────────────────────────────────────────────────────────────

    @app_commands.command(name="skip", description="⏭️ Skip the current song")
    async def skip(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client
        gq = get_queue(interaction.guild.id)
        if not player or not gq.current:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ No song is playing!", color=config.ERROR_COLOR),
                ephemeral=True,
            )
            return
        gq.skip_requested = True
        # NOTE: wavelink.Player has no `.skip()` method — this was the bug.
        # Stopping the current track fires on_wavelink_track_end, which
        # advances the queue for us.
        await player.stop()
        await interaction.response.send_message(
            embed=discord.Embed(description="⏭️ Song skipped.", color=config.SUCCESS_COLOR)
        )

    # ── /stop ────────────────────────────────────────────────────────────────

    @app_commands.command(name="stop", description="⏹️ Stop the music and clear the queue")
    async def stop(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client
        gq = get_queue(interaction.guild.id)
        gq.queue.clear()
        gq.current = None
        gq.loop = False
        if player and player.playing:
            await player.stop()
        embed = discord.Embed(
            description="⏹️ Music stopped and queue cleared.",
            color=config.ERROR_COLOR,
        )
        await interaction.response.send_message(embed=embed)
        await self._refresh_panel(gq)

    # ── /pause ───────────────────────────────────────────────────────────────

    @app_commands.command(name="pause", description="⏸️ Pause the music")
    async def pause(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client
        if player and player.playing and not player.paused:
            await player.pause(True)
            await interaction.response.send_message(
                embed=discord.Embed(description="⏸️ Paused.", color=config.WARNING_COLOR)
            )
            await self._refresh_panel(get_queue(interaction.guild.id))
        else:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ No song is playing!", color=config.ERROR_COLOR),
                ephemeral=True,
            )

    # ── /resume ──────────────────────────────────────────────────────────────

    @app_commands.command(name="resume", description="▶️ Resume the music")
    async def resume(self, interaction: discord.Interaction):
        player: wavelink.Player = interaction.guild.voice_client
        if player and player.paused:
            await player.pause(False)
            await interaction.response.send_message(
                embed=discord.Embed(description="▶️ Music resumed.", color=config.SUCCESS_COLOR)
            )
            await self._refresh_panel(get_queue(interaction.guild.id))
        else:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Music isn't paused!", color=config.ERROR_COLOR),
                ephemeral=True,
            )

    # ── /queue ───────────────────────────────────────────────────────────────

    @app_commands.command(name="queue", description="📋 Show the song queue")
    async def queue_cmd(self, interaction: discord.Interaction):
        gq = get_queue(interaction.guild.id)

        embed = discord.Embed(
            title="📋 Song Queue",
            color=config.EMBED_COLOR,
            timestamp=datetime.now(),
        )

        if gq.current:
            t = gq.current.track
            embed.add_field(
                name="🎵 Now Playing",
                value=f"**[{t.title}]({t.uri or ''})** `{_fmt(t.length)}`",
                inline=False,
            )
        else:
            embed.add_field(name="🎵 Now Playing", value="`No song playing`", inline=False)

        if gq.queue:
            lines = []
            for i, item in enumerate(list(gq.queue)[:10], 1):
                t = item.track
                lines.append(f"`{i}.` **[{t.title}]({t.uri or ''})** `{_fmt(t.length)}`")
            if len(gq.queue) > 10:
                lines.append(f"*...and {len(gq.queue) - 10} more songs*")
            embed.add_field(name="📋 Queue", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="📋 Queue", value="`Queue is empty`", inline=False)

        embed.add_field(name="🔁 Loop", value="✅ On" if gq.loop else "❌ Off", inline=True)
        embed.add_field(name="🔊 Volume", value=f"{gq.volume}%", inline=True)
        embed.add_field(name="📊 Total in Queue", value=f"{len(gq.queue)} songs", inline=True)
        embed.set_footer(text=f"{config.BOT_NAME} | Dev: {config.DEVELOPER}")
        await interaction.response.send_message(embed=embed)

    # ── /nowplaying ───────────────────────────────────────────────────────────

    @app_commands.command(name="nowplaying", description="🎵 Show info about the current song")
    async def nowplaying(self, interaction: discord.Interaction):
        gq = get_queue(interaction.guild.id)
        if not gq.current:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ No song is playing!", color=config.ERROR_COLOR),
                ephemeral=True,
            )
            return
        embed = self._now_playing_embed(gq)
        embed.timestamp = datetime.now()
        embed.add_field(name="📋 In queue", value=f"{len(gq.queue)} upcoming songs", inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /volume ───────────────────────────────────────────────────────────────

    @app_commands.command(name="volume", description="🔊 Set the volume level (0-100)")
    @app_commands.describe(level="Volume level, from 0 to 100")
    async def volume(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 100]):
        gq = get_queue(interaction.guild.id)
        gq.volume = level
        player: wavelink.Player = interaction.guild.voice_client
        if player and player.connected:
            await player.set_volume(level)
        embed = discord.Embed(
            description=f"🔊 Volume set to **{level}%**",
            color=config.SUCCESS_COLOR,
        )
        await interaction.response.send_message(embed=embed)
        await self._refresh_panel(gq)

    # ── /loop ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="loop", description="🔁 Toggle song loop on/off")
    async def loop(self, interaction: discord.Interaction):
        gq = get_queue(interaction.guild.id)
        gq.loop = not gq.loop
        state = "✅ On" if gq.loop else "❌ Off"
        embed = discord.Embed(
            description=f"🔁 Loop: **{state}**",
            color=config.SUCCESS_COLOR if gq.loop else config.ERROR_COLOR,
        )
        await interaction.response.send_message(embed=embed)
        await self._refresh_panel(gq)

    # ── /panel ────────────────────────────────────────────────────────────────

    @app_commands.command(name="panel", description="🎛️ Open a full music control panel (buttons)")
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
