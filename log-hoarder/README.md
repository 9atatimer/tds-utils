# log-hoarder

Automatic terminal session logging via tmux. Every pane gets its own log.
Logs are captured live, archived on pane exit, and eventually branded with a
human-readable slug by a local LLM.

## How it works

```
Terminal opens
  → zshrc launches tmux new-session
    → session-created hook fires tmux_logging.sh
      → pipe-pane opens: PTY output → ansifilter → active/SESSION/WINDOW/PANE/HHMMSS.log

Pane exits (shell exit or Ctrl-D)
  → pane-exited hook fires tmux_shepherd.sh SESSION WINDOW PANE
    → pane log dir moved: active/ → archived/
    → orphan sweep: any active/ dirs whose session is dead are also archived

Cron runs tmux_shepherd.sh (no args)
  → sweeps archived/ for unbranded pane dirs (no slug.txt)
    → calls log_brander <panedir>
      → local LLM samples the log, writes slug.txt
```

Force-killed panes (`Prefix-x`) do not fire `pane-exited`. Their logs remain
in `active/` until the orphan sweep picks them up on the next pane exit or
cron run.

When `TDS_LOG_DIR` is unset, logging is suppressed but diagnostic output is
still written to `~/log-hoarder.logging.log` (and `~/log-hoarder.shepherd.*.log`
for the shepherd).

---

## Files

| File | Purpose |
|------|---------|
| `tmux.conf` | tmux hooks — symlink to `~/.tmux.conf` |
| `tmux_logging.sh` | Opens pipe-pane at pane creation |
| `tmux_shepherd.sh` | Archives logs on exit; sweeps orphans; delegates branding to cron |
| `log_brander` | Stub — samples log, calls local LLM, writes `slug.txt` |

---

## Prerequisites

```sh
brew install tmux ansifilter
```

---

## Wiring it up

### 1. Set your log directory

In `macos/dot.zshenv`, set:

```sh
export TDS_LOG_DIR="$HOME/.local/share/log-hoarder"
```

Then create the directories:

```sh
mkdir -p "$TDS_LOG_DIR/active"
mkdir -p "$TDS_LOG_DIR/archived"
```

### 2. Symlink the scripts into tds-utils/bin/

The tmux hooks reference `~/workplace/tds-utils/bin/` directly (which is on `$PATH`).

```sh
chmod +x ~/workplace/tds-utils/log-hoarder/tmux_logging.sh
chmod +x ~/workplace/tds-utils/log-hoarder/tmux_shepherd.sh
chmod +x ~/workplace/tds-utils/log-hoarder/log_brander

cd ~/workplace/tds-utils/bin
ln -sf ../log-hoarder/tmux_logging.sh  tmux_logging.sh
ln -sf ../log-hoarder/tmux_shepherd.sh tmux_shepherd.sh
ln -sf ../log-hoarder/log_brander      log_brander
```

### 3. Symlink tmux.conf

If you have no existing `~/.tmux.conf`:

```sh
ln -sf ~/workplace/tds-utils/log-hoarder/tmux.conf ~/.tmux.conf
```

If you already have a `~/.tmux.conf`, add this line to it instead:

```
source-file ~/workplace/tds-utils/log-hoarder/tmux.conf
```

### 4. Set Terminal to auto-launch tmux

In Terminal.app: **Preferences → Profiles → Shell → Startup**

Set "Run command" to:

```
/bin/zsh -l
```

The `dot.zshrc` already contains the tmux auto-launch guard:

```zsh
if [[ -o interactive ]] && [[ -z "$TMUX" ]]; then
    exec tmux new-session
fi
```

### 5. Add the cron job

```sh
crontab -e
```

Add:

```
0 * * * * /bin/zsh -l -c '~/workplace/tds-utils/bin/tmux_shepherd.sh'
```

This runs the straggler sweep hourly. The `-l` flag ensures `TDS_LOG_DIR` is
loaded from your login environment.

### 6. Activate log_brander (when ready)

When you have a local model running (e.g. Ollama), set in `dot.zshenv`:

```sh
export LLM_ENDPOINT="http://localhost:11434/api/generate"
export LLM_MODEL="mistral"   # or whichever model you're running
```

Then uncomment the curl block in `log_brander` and remove the stub exit.

---

## Verifying it works

Open a new terminal. You should see a tmux session start. Then:

```sh
# Check a log is being written
ls -la $TDS_LOG_DIR/active/

# Check the pipe is open on the current pane
tmux display -p '#{?pane_pipe,pipe open,no pipe}'
```

Close the terminal. Check the log moved:

```sh
ls -la $TDS_LOG_DIR/archived/
```

---

## Dismantling it

### Stop new sessions from logging

Remove or comment out the hooks in `tmux.conf` (or your `~/.tmux.conf`):

```
# set-hook -g session-created    ...
# set-hook -g after-new-window   ...
# set-hook -g after-split-window ...
# set-hook -g pane-exited        ...
```

Reload tmux config:

```sh
tmux source-file ~/.tmux.conf
```

### Stop tmux auto-launching in new terminals

Comment out the guard block in `macos/dot.zshrc`:

```zsh
# if [[ -o interactive ]] && [[ -z "$TMUX" ]]; then
#     exec tmux new-session
# fi
```

### Remove the cron job

```sh
crontab -e
# delete the tmux_shepherd.sh line
```

### Remove symlinks

```sh
rm ~/workplace/tds-utils/bin/tmux_logging.sh
rm ~/workplace/tds-utils/bin/tmux_shepherd.sh
rm ~/workplace/tds-utils/bin/log_brander
rm ~/.tmux.conf   # or remove the source-file line if you kept your own
```

### Remove log directory

Only do this if you no longer need the logs:

```sh
rm -rf "$TDS_LOG_DIR"
```

### Unset environment variables

In `macos/dot.zshenv`, remove or comment out:

```sh
# export TDS_LOG_DIR="$HOME/.local/share/log-hoarder"
# export LLM_ENDPOINT=""
# export LLM_MODEL=""
```
