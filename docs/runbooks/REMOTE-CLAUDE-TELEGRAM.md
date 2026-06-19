# Remote / Hands-Free Claude Code over Telegram Runbook

Drive Claude Code from your phone while away from the desk -- text it from
anywhere, and (with two free phone tricks) talk to it and hear it back on a
jog. This uses **Claude Code Channels** (Anthropic's first-party feature, in
research preview), not a third-party app, and costs **$0** beyond your
existing Claude subscription. No ElevenLabs, no cloud voice, no extra paid
service.

## The one thing to understand first

**Nothing runs in the cloud.** A "channel" is a local MCP server that Claude
Code spawns as a subprocess; for Telegram it *polls* the Bot API from your
machine. The agent, your repo, and every tool call run on **your Mac**, which
must stay **awake, lid open, plugged in, on Wi-Fi** for the whole session.
Your phone is a remote control, not a host. Close the session or let the Mac
sleep and the bot goes silent. (`happy` / ElevenLabs and the various
`*-voice` MCP servers have this exact same constraint -- none of them give you
cloud execution.)

## TL;DR -- daily use, once installed

```sh
# at your desk, in the repo you want to drive:
jog-claude                 # careful mode: pauses on tool-permission prompts
jog-claude-yolo            # unattended: --dangerously-skip-permissions (trusted repos ONLY)
```

Then DM `@jogBitBot` from your phone. The aliases live in
`macos/dot.alias` and route through `clai` for telemetry:

```sh
alias jog-claude='clai claude --channels plugin:telegram@claude-plugins-official'
alias jog-claude-yolo='clai claude --channels plugin:telegram@claude-plugins-official --dangerously-skip-permissions'
```

**Config is user-global, not per-repo.** Token, pairing, and allowlist live
under `~/.claude/channels/telegram/`, so `jog-claude` works from any repo and
you never re-pair. Only the *cwd* changes per session.

## The free hands-free stack (proven working)

| Leg | How | Cost |
| --- | --- | --- |
| Voice **IN** | Phone **keyboard dictation** mic -> types text -> send. The *phone* does the STT locally. | $0 |
| Brain | `jog-claude` on the Mac, real tool calls in the cwd. | $0 |
| Voice **OUT** | Notification-reader app (**ReadItToMe** / **Shouter**) reads incoming Telegram aloud through any Bluetooth buds. | $0 |

Notes:
- **Voice IN -- use keyboard dictation, not Telegram voice notes.** Dictation
  ships *text*; the Mac needs nothing. A Telegram *voice note* ships an `.oga`
  audio file (Bot API does **not** transcribe for bots), so the Mac would need
  a local Whisper (`uv tool install mlx-whisper`) to read it. Only bother with
  Whisper if press-and-hold feels better than the keyboard mic mid-stride.
- **Voice OUT on Samsung:** the native "Read notifications aloud" is
  **Galaxy-Buds-only** (Galaxy Wearable -> Buds -> Notifications; reads only
  while screen locked). With cheap generic buds, use a reader app instead --
  don't buy $250 Buds3 Pro to dodge a free app.
- Voice OUT on iOS (for reference): Settings -> Notifications -> Announce
  Notifications + headphones.

## First-time install

Prereqs: Claude Code **v2.1.80+** (v2.1.81+ for permission relay), signed in
with a **claude.ai account** (channels do **not** work with an API-key-only /
console login), and **Bun** (`brew install bun`).

```sh
# inside a Claude Code session:
/plugin install telegram@claude-plugins-official
/reload-plugins
```

**Install it at *user* scope, not project/local.** The interactive `/plugin`
flow can pin the plugin to the repo you ran it in (`"scope": "local"` plus a
`projectPath`). When that happens it goes **silently dead in every other
repo** -- `jog-claude` still appends `--channels` but the plugin isn't active
there, so no poller spawns and no error prints (see Failure signature 3). The
CLI form forces global scope:
```sh
claude plugin install telegram@claude-plugins-official --scope user   # --scope user is the default
```

Bot + token (one-time):
1. Telegram -> `@BotFather` -> `/newbot` -> name -> username ending in `bot` ->
   copy the token (`123456789:AAH...`).
2. Save the token. The configure command (`/telegram:configure <token>`)
   just writes the file below -- you can write it by hand instead:
   ```
   ~/.claude/channels/telegram/.env
   TELEGRAM_BOT_TOKEN=123456789:AAH...
   ```
3. Sanity-check the token without leaking it:
   ```sh
   set -a; . ~/.claude/channels/telegram/.env; set +a
   curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe"   # -> {"ok":true,...}
   ```

Pair + lock (one-time):
```sh
# relaunch WITH the channel so the server polls:
jog-claude
# DM the bot anything -> it replies with a pairing code, then in the session:
/telegram:access pair <code>
/telegram:access policy allowlist     # lock to your sender ID only
```

**Always set `policy allowlist`.** Under the default `pairing` policy anyone
can DM the bot and queue a pairing request. With `jog-claude-yolo`, the only
thing authorized to run arbitrary commands on your Mac is whoever is on the
allowlist -- that list is your perimeter.

## How to recognize you have the wrong setup

**Failure signature 1 -- `Failed to reconnect to plugin:telegram:telegram: -32000`**
The channel MCP server started with **no token** and exited before the MCP
handshake. Fix: write `~/.claude/channels/telegram/.env` (above) and relaunch
with `--channels`. Confirm the server actually runs the token check:
```sh
P=~/.claude/plugins/cache/claude-plugins-official/telegram/*/
CLAUDE_PLUGIN_ROOT=$P timeout 5 bun run --cwd $P --shell=bun --silent start
# good token -> stays running; missing token -> "TELEGRAM_BOT_TOKEN required"
```

**Failure signature 2 -- bot is silent, no reply, no pairing code**
Two pollers are fighting for the single Telegram `getUpdates` slot (Telegram
allows only one). Usually a **stale orphaned server** from a prior session
(`ppid 1`) is squatting. Diagnose and fix:
```sh
# is a webhook hijacking updates? (safe; does NOT consume the pairing message)
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"   # url should be empty
#   pending_update_count > 0 with no consumer == nobody is polling cleanly

# find orphan / duplicate channel servers:
ps -Ao pid,ppid,lstart,command | grep -E '[s]erver\.ts|[c]hannels plugin:telegram'
kill <orphan-pid>                                   # the ppid 1 bun server.ts
rm -f ~/.claude/plugins/cache/claude-plugins-official/telegram/*/.in_use/*   # stale lock
```
Then relaunch a single `jog-claude`. **NEVER call `getUpdates` yourself while
a session is running** -- it steals the pairing message (or 409s) and breaks
pairing.

**Golden rule: one Telegram session at a time.** Before starting `jog-claude`
in a new repo, **exit the old session first**, or you recreate signature 2.

**Failure signature 3 -- worked in one repo, dead silent in another (wrong install scope)**
The plugin was installed at `local`/`project` scope, pinned to one repo's
path. `jog-claude` from a *different* repo still passes `--channels`, but the
plugin isn't active there, so the `bun server.ts` poller **never spawns** --
no 409, no error, no pairing code, just silence. The tell is that
`installed_plugins.json` shows `"scope": "local"` with a `projectPath`, and
there is **no `bun server.ts` process running** at all (contrast signature 2,
where there are *too many* pollers). Diagnose:
```sh
# what scope(s) is the plugin installed at?
python3 -c "import json; d=json.load(open('$HOME/.claude/plugins/installed_plugins.json')); [print(e['scope'], '->', e.get('projectPath', '(global)')) for e in d['plugins']['telegram@claude-plugins-official']]"
#   local -> /Users/you/workplace/other-repo   <- the trap
#   user  -> (global)                           <- what you want

# is the poller even running in this session?
ps -Ao pid,ppid,command | grep -E '[s]erver\.ts'   # empty == nothing is polling
```
Fix -- (re)install at user scope, then **restart the session** (plugin scope
changes don't apply to a live session):
```sh
claude plugin install telegram@claude-plugins-official --scope user
# optional cleanup of the misscoped entry:
claude plugin uninstall telegram@claude-plugins-official --scope local
```
Channel state (`.env`, `access.json`) is separate from the plugin and
survives the reinstall, so you do **not** re-pair or re-enter the token.

## Where state lives (all user-global)

```
~/.claude/channels/telegram/.env              # bot token  (secret; never commit)
~/.claude/channels/telegram/access.json       # dmPolicy, allowFrom[], pending{}
~/.claude/channels/telegram/approved/<id>     # marker the server polls to say "you're in"
~/.claude/channels/telegram/inbox/*.oga       # downloaded voice notes (if used)
~/.claude/plugins/cache/claude-plugins-official/telegram/<ver>/   # the plugin + bun server
```

## Bot of record

Current bot: **@jogBitBot** (`claude-telegram-bot`). To rotate, make a new
bot in BotFather and replace `TELEGRAM_BOT_TOKEN` in the `.env`.
