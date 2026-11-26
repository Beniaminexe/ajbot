import asyncio
import logging
import os
import discord
from discord.ext import commands
import requests
import wavelink

log = logging.getLogger("ajbot")

# ------------- ENV -------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

GITHUB_USER = os.getenv("GITHUB_USER", "Beniaminexe")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


# ------------- CLIENTS -------------

intents = discord.Intents.default()
intents.message_content = True
bot =commands.Bot(command_prefix="/", intents=intents, case_insensitive=True)


def github_headers():
    h = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h

# ------------- EVENTS -------------

# Only ONE on_ready may exist: a second @bot.event with the same name
# silently replaces the first (that is why the presence never showed).
@bot.event
async def on_ready():
    # Prevent multiple connections if Discord reconnects
    if getattr(bot, "lavalink_ready", False):
        return

    bot.lavalink_ready = True
    log.info("Logged in as %s (id: %s)", bot.user, bot.user.id)
    await bot.change_presence(activity=discord.Game(name="music | /play"))

    # Connect to the Lavalink node (the container named 'lavalink')
    await wavelink.Pool.connect(
        nodes=[
            wavelink.Node(
                uri="http://lavalink:2333",
                password="youshallnotpass",
            )
        ],
        client=bot,
    )

    log.info("Lavalink connect requested.")


# ------------- LAVALINK EVENTS (visibility) -------------
# Without these, a failed voice connection is completely silent.

@bot.event
async def on_wavelink_node_ready(payload: wavelink.NodeReadyEventPayload):
    log.info("Lavalink node %s ready (resumed=%s)", payload.node.identifier, payload.resumed)

    if payload.resumed:
        return  # same Lavalink process came back within the resume window: players survived

    # Fresh Lavalink session (container restarted/recreated). Lavalink has forgotten every
    # player, but this bot still remembers being in voice. Drop that stale state so the
    # next /play starts clean instead of joining and instantly leaving.
    for vc in list(bot.voice_clients):
        if isinstance(vc, wavelink.Player):
            log.warning("Lavalink restarted: dropping stale player in guild %s", vc.guild.id)
            try:
                await vc.disconnect()
            except Exception:
                log.exception("Could not drop stale player in guild %s", vc.guild.id)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    # Replaces discord.py's default handler, which only printed to the console:
    # users spamming /play got no reply at all when something broke.
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send(f"Missing `{error.param.name}`. Example: `/play never gonna give you up`")
    if isinstance(error, (commands.MissingPermissions, commands.BotMissingPermissions)):
        return await ctx.send(str(error))
    log.error("Command %s failed", ctx.command, exc_info=error)
    await ctx.send("⚠️ That didn't work. Try again; if it keeps failing, check the bot logs.")


@bot.event
async def on_wavelink_websocket_closed(payload: wavelink.WebsocketClosedEventPayload):
    # Discord closed the VOICE connection. Code 4017 = client lacks DAVE (E2EE) support.
    log.warning(
        "Discord voice connection closed: code=%s reason=%r by_remote=%s",
        payload.code, payload.reason, payload.by_remote,
    )


@bot.event
async def on_wavelink_track_exception(payload: wavelink.TrackExceptionEventPayload):
    title = payload.track.title if payload.track else None
    log.error("Track exception on %r: %s", title, payload.exception)


@bot.event
async def on_wavelink_track_stuck(payload: wavelink.TrackStuckEventPayload):
    log.warning("Track stuck on %r (threshold %sms)", payload.track.title, payload.threshold)


# ------------- COMMANDS -------------

@bot.command(name="ping")
async def ping(ctx):
    await ctx.send("Pong! ✅ Bot is alive on Proxmox.")

@bot.command(name="ghcommits")
async def gh_commits(ctx, repo: str = None):
    """Show last 3 commits from a GitHub repo. Usage: !ghcommits [user/repo or repo]"""
    if repo is None:
        if not GITHUB_REPO:
            await ctx.send("No default repo configured. Use `!ghcommits user/repo`.")
            return
        full_repo = f"{GITHUB_USER}/{GITHUB_REPO}"
    else:
        if "/" in repo:
            full_repo = repo
        else:
            full_repo = f"{GITHUB_USER}/{repo}"

    url = f"https://api.github.com/repos/{full_repo}/commits?per_page=3"
    try:
        r = requests.get(url, headers=github_headers(), timeout=10)
        if r.status_code != 200:
            await ctx.send(f"GitHub API returned {r.status_code} for `{full_repo}`.")
            return

        commits = r.json()
        if not commits:
            await ctx.send(f"No commits found for `{full_repo}`.")
            return

        lines = [f"**Last commits for `{full_repo}`:**"]
        for c in commits:
            sha = c["sha"][:7]
            msg = c["commit"]["message"].split("\n")[0]
            author = c["commit"]["author"]["name"]
            lines.append(f"- `{sha}` by **{author}** – {msg}")

        await ctx.send("\n".join(lines))
    except Exception as e:
        await ctx.send(f"Error talking to GitHub: `{e}`")


@bot.command(name="play", aliases=["p"])
async def play(ctx: commands.Context, *, query: str):
    # User must be in a voice channel
    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("You need to be in a voice channel first.")

    channel = ctx.author.voice.channel

    # Get or create a Wavelink player
    if ctx.voice_client and isinstance(ctx.voice_client, wavelink.Player):
        player: wavelink.Player = ctx.voice_client
    else:
        try:
            player: wavelink.Player = await channel.connect(cls=wavelink.Player)
        except wavelink.ChannelTimeoutException:
            log.exception("Voice connect to %s timed out", channel)
            return await ctx.send("I couldn't join the voice channel (timed out).")

    # partial = play the next queued track automatically, no recommendations.
    # (default is disabled, which meant queued songs never started)
    player.autoplay = wavelink.AutoPlayMode.partial

    # Search YouTube via Lavalink
    # This works with plain text (song name) OR a direct URL.
    tracks: wavelink.Search = await wavelink.Playable.search(
        query,
        source="ytsearch"  # use YouTube search
    )

    if not tracks:
        return await ctx.send("I couldn't find anything for that query.")

    track = tracks[0]

    # If something is already playing, queue it instead
    if player.playing:
        await player.queue.put_wait(track)
        return await ctx.send(f"Queued: `{track.title}`")

    # Otherwise start playing immediately
    await player.play(track)
    await ctx.send(f"Now playing: `{track.title}`")

@bot.command(name="skip")
async def skip(ctx: commands.Context):
    if not ctx.voice_client or not isinstance(ctx.voice_client, wavelink.Player):
        return await ctx.send("I'm not in a voice channel.")
    await ctx.voice_client.stop()
    await ctx.send("Skipped.")

@bot.command(name="stop")
async def stop(ctx: commands.Context):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("Disconnected from voice.")


@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True)
async def clear(ctx: commands.Context, amount: int = 50):
    """
    Clear recent messages in the current text channel.

    Usage:
      !clear          -> clears last 50 messages
      !clear 10       -> clears last 10 messages
      !clear 100      -> clears last 100 messages
    """
    # basic sanity check
    if amount <= 0:
        await ctx.send("❌ Amount must be a positive number.")
        return

    # Discord bulk delete hard limit is 100
    if amount > 100:
        amount = 100

    # +1 to also delete the command message itself
    deleted = await ctx.channel.purge(limit=amount + 1)

    # deleted includes the command; subtract 1 for “real” cleared messages
    cleared = max(len(deleted) - 1, 0)

    msg = await ctx.send(f"🧹 Cleared `{cleared}` messages in {ctx.channel.mention}.")
    # remove the confirmation after a short delay to keep things tidy
    await asyncio.sleep(5)
    await msg.delete()
    
    

# ------------- RUN -------------

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN not set.")
    bot.run(DISCORD_TOKEN)


