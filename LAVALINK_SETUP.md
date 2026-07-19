# Running Lavalink for the music system

`/play` and the rest of the music commands now stream through **Lavalink**
instead of yt-dlp/ffmpeg on the bot's own machine — better audio quality,
way less CPU/bandwidth on your server, and it survives restarts better.

The bot only *talks* to Lavalink over the network — Lavalink itself is a
separate program (Java) that you run once, next to the bot or on its own
box. This file is about getting that program running.

## 1. Requirements

- **Java 17 or newer** — `java -version` to check. Install via your OS
  package manager (`apt install openjdk-17-jre-headless` on Debian/Ubuntu)
  or from [adoptium.net](https://adoptium.net).

## 2. Download Lavalink

Grab the latest `Lavalink.jar` from the
[Lavalink releases page](https://github.com/lavalink-devs/Lavalink/releases)
and put it in its own folder, e.g. `lavalink/Lavalink.jar`.

## 3. `application.yml`

In that same folder, create `application.yml`:

```yaml
server:
  port: 2333
  address: 127.0.0.1   # 0.0.0.0 if Lavalink runs on a different machine/container than the bot

lavalink:
  plugins:
    - dependency: "dev.lavalink.youtube:youtube-plugin:1.18.0"
      repository: "https://maven.lavalink.dev/releases"
  server:
    password: "youshallnotpass"   # change this, then match it in your .env below
    sources:
      youtube: false   # the OLD built-in source — must be off, the plugin above replaces it
      soundcloud: true
      bandcamp: true
      twitch: true
      vimeo: true
      http: true
    plugins:
      youtube:
        enabled: true
        allowSearch: true
        clients:
          - MUSIC
          - WEB
          - WEBEMBEDDED
          - ANDROID_VR
          - TVHTML5EMBEDDED
```

**Important:** as of Lavalink v4, the old built-in YouTube support is
deprecated and disabled by default — you *must* add the `youtube-source`
plugin block above (`sources.youtube: false` + `lavalink.plugins` +
`plugins.youtube`) or `/play` will fail to find anything on YouTube.
SoundCloud/Bandcamp/etc. work out of the box without a plugin, so those are
a good way to sanity-check Lavalink is reachable even before the YouTube
plugin is configured right.

If YouTube playback still gets rate-limited/blocked after this, the plugin
supports OAuth login for more reliable access — see the
[youtube-source README](https://github.com/lavalink-devs/youtube-source)
(`oauth:` section) for that; it's optional but worth doing if `/play` starts
failing on YouTube links specifically.

## 4. Run it

```
cd lavalink
java -jar Lavalink.jar
```

Leave that running (use `screen`, `tmux`, a systemd service, or Docker if
this is on a always-on host). You should see a `Lavalink is ready to accept
connections.` line in its logs.

## 5. Point the bot at it

In your `.env` (same folder as `main.py`'s parent, per `config.py`):

```
LAVALINK_HOST=127.0.0.1
LAVALINK_PORT=2333
LAVALINK_PASSWORD=youshallnotpass
LAVALINK_SECURE=false
```

Match `LAVALINK_PASSWORD` to whatever you set in `application.yml`. If
Lavalink is on a different machine, set `LAVALINK_HOST` to its address, and
`LAVALINK_SECURE=true` if you're connecting over HTTPS/WSS (e.g. behind a
reverse proxy with TLS).

Restart the bot after this — the console will print `✅ Lavalink node
connected` on success, or a `⚠️ Lavalink node connection failed` line with
the reason if something's off (wrong port, Lavalink not started yet, wrong
password, etc.). Every other part of the bot keeps working even if this
fails — only the music commands are affected.
