import os
import discord
from discord.ext import commands
from proxmoxer import ProxmoxAPI
import requests
import wavelink

# ------------- ENV -------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

PVE_HOST = os.getenv("PVE_HOST")
PVE_USER = os.getenv("PVE_USER")
PVE_TOKEN_NAME = os.getenv("PVE_TOKEN_NAME")
PVE_TOKEN_VALUE = os.getenv("PVE_TOKEN_VALUE")
#PVE_NODE = os.getenv("PVE_NODE", PVE_HOST)

GITHUB_USER = os.getenv("GITHUB_USER", "Beniaminexe")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


# ------------- CLIENTS -------------

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


def get_proxmox():
    """Return a ProxmoxAPI client."""
    return ProxmoxAPI(
        PVE_HOST,
        user=PVE_USER,
        token_name=PVE_TOKEN_NAME,
        token_value=PVE_TOKEN_VALUE,
        verify_ssl=False
    )


def github_headers():
    h = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h

# ------------- EVENTS -------------

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="with Proxmox & GitHub"))

@bot.event
async def on_ready():
    # Prevent multiple connections if Discord reconnects
    if getattr(bot, "lavalink_ready", False):
        return

    bot.lavalink_ready = True
    print(f"Logged in as {bot.user} (id: {bot.user.id})")

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

    print("Lavalink node connected.")


# ------------- COMMANDS -------------

@bot.command(name="ping")
async def ping(ctx):
    await ctx.send("Pong! ✅ Bot is alive on Proxmox.")

@bot.command(name="pve")
async def pve_status(ctx):
    """Show basic Proxmox node status."""
    try:
        proxmox = get_proxmox()
        nodes = proxmox.nodes.get()
        if not nodes:
            await ctx.send("Could not fetch nodes from Proxmox.")
            return

        lines = []
        for n in nodes:
            name = n.get("node")
            cpu = round(n.get("cpu", 0) * 100, 1)
            mem_used = n.get("memory", 0)
            mem_total = n.get("maxmem", 1)
            mem_pct = round(mem_used / mem_total * 100, 1)
            lines.append(f"**{name}**: CPU `{cpu}%`, RAM `{mem_pct}%`")

        await ctx.send("\n".join(lines))
    except Exception as e:
        await ctx.send(f"Error talking to Proxmox: `{e}`")


@bot.command(name="vms")
async def list_vms(ctx):
    """List running VMs/containers."""
    try:
        proxmox = get_proxmox()
        msg_lines = []
        for node in proxmox.nodes.get():
            node_name = node["node"]
            qemu_vms = proxmox.nodes(node_name).qemu.get()
            lxcs = proxmox.nodes(node_name).lxc.get()

            running = [vm for vm in qemu_vms if vm.get("status") == "running"]
            running_lxc = [c for c in lxcs if c.get("status") == "running"]

            if not running and not running_lxc:
                msg_lines.append(f"**{node_name}**: no running guests.")
                continue

            msg_lines.append(f"**{node_name}**:")
            for vm in running:
                msg_lines.append(f"- VM {vm['vmid']}: {vm.get('name', 'no-name')} (QEMU)")
            for c in running_lxc:
                msg_lines.append(f"- CT {c['vmid']}: {c.get('name', 'no-name')} (LXC)")
        await ctx.send("\n".join(msg_lines))
    except Exception as e:
        await ctx.send(f"Error listing VMs: `{e}`")


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
@bot.command(name="startvm")
async def startvm(ctx, vmid: int):
    """Start a VM by ID and announce it."""
    try:
        proxmox = get_proxmox()
        nodes = proxmox.nodes.get()
        if not nodes:
            await ctx.send("I couldn't find any Proxmox nodes. 🤔")
            return

        node_name = nodes[0]["node"]  # assumes single-node cluster
        proxmox.nodes(node_name).qemu(vmid).status.start.post()

        await ctx.send(f"▶️ Start requested for VM `{vmid}` on node `{node_name}`.")
    except Exception as e:
        await ctx.send(f"❌ Failed to start VM `{vmid}`: `{e}`")


@bot.command(name="stopvm")
async def stopvm(ctx, vmid: int):
    """Shut down a VM by ID and announce it."""
    try:
        proxmox = get_proxmox()
        nodes = proxmox.nodes.get()
        if not nodes:
            await ctx.send("I couldn't find any Proxmox nodes. 🤔")
            return

        node_name = nodes[0]["node"]
        # graceful shutdown instead of hard stop
        proxmox.nodes(node_name).qemu(vmid).status.shutdown.post()

        await ctx.send(f"⏹ Shutdown requested for VM `{vmid}` on node `{node_name}`.")
    except Exception as e:
        await ctx.send(f"❌ Failed to stop VM `{vmid}`: `{e}`")

@bot.command(name="play")
async def play(ctx: commands.Context, *, query: str):
    # User must be in a voice channel
    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("You need to be in a voice channel first.")

    channel = ctx.author.voice.channel

    # Get or create a Wavelink player
    if ctx.voice_client and isinstance(ctx.voice_client, wavelink.Player):
        player: wavelink.Player = ctx.voice_client
    else:
        player: wavelink.Player = await channel.connect(cls=wavelink.Player)

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


@bot.command(name="mcup")
async def mcup(ctx: commands.Context):
    """Start the Minecraft server VM (vmid 301) on your Proxmox node."""
    vmid = 301

    try:
        proxmox = get_proxmox()
        nodes = proxmox.nodes.get()
        if not nodes:
            await ctx.send("I couldn't find any Proxmox nodes. 🤔")
            return

        node_name = nodes[0]["node"]  # used internally only

        await ctx.send(
            f"🟡 Starting Minecraft server VM (ID `{vmid}`)..."
        )

        proxmox.nodes(node_name).qemu(vmid).status.start.post()

        await ctx.send("🟢 Minecraft server VM is starting up!")
    except Exception as e:
        await ctx.send(f"🔴 Failed to start VM `{vmid}`:\n```{e}```")


@bot.command(name="mcdown")
async def mcdown(ctx: commands.Context):
    """Shut down the Minecraft server VM (vmid 301) on your Proxmox node."""
    vmid = 301

    try:
        proxmox = get_proxmox()
        nodes = proxmox.nodes.get()
        if not nodes:
            await ctx.send("I couldn't find any Proxmox nodes. 🤔")
            return

        node_name = nodes[0]["node"]  # used internally only

        await ctx.send(
            f"🟡 Shutting down Minecraft server VM (ID `{vmid}`)..."
        )

        # Graceful ACPI shutdown
        proxmox.nodes(node_name).qemu(vmid).status.shutdown.post()
        # For a hard poweroff, you'd use:
        # proxmox.nodes(node_name).qemu(vmid).status.stop.post()

        await ctx.send("🟢 Shutdown signal sent. The VM should power off shortly.")
    except Exception as e:
        await ctx.send(f"🔴 Failed to shut down VM `{vmid}`:\n```{e}```")




# ------------- RUN -------------

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN not set.")
    bot.run(DISCORD_TOKEN)


