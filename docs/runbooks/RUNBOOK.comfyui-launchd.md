# RUNBOOK: ComfyUI under launchd with a unified-memory cap

Issue: 9atatimer/tds-utils#338. Files: `bin/launch-comfyui`,
`macos/launchd/com.tds.comfyui.plist`, `test/smoketest_comfyui_launchd.sh`.

## Why this exists

- A Flux2 workflow in Comfy Desktop took the M1 Max (64 GB) down: UI
  frozen, heavy pageouts, hard stop.
- On Apple Silicon "VRAM" is unified memory. PyTorch's MPS allocator ships
  with `PYTORCH_MPS_HIGH_WATERMARK_RATIO=1.7`: it allocates up to 170% of
  Metal's recommended working set (51.84 GB on this box, so about 88 GB)
  before refusing. The kernel swaps long before that.
- ComfyUI's memory planner on MPS reads psutil free memory and does not
  know GPU and OS share one pool.
- Nothing outside the process can cap it. Linux containers (docker,
  podman, Apple `container`) have no Metal. The macOS sandbox (seatbelt)
  has no resource quotas. rlimits ignore wired GPU memory. A macOS VM
  (Tart) is the only external wall, at a speed cost, and is the fallback
  if this proves insufficient.
- So the cap is set in-process, from one knob, and ComfyUI's planner and
  torch's allocator are told the same ceiling.

## The one knob

- `COMFYUI_BUDGET_GB` (default 48): unified memory ComfyUI's GPU side may
  take. The launcher derives:
  - `PYTORCH_MPS_HIGH_WATERMARK_RATIO = budget / torch.mps.recommended_max_memory()`
  - `PYTORCH_MPS_LOW_WATERMARK_RATIO = high - 0.10`
  - `--reserve-vram = total RAM - budget`
- 48 of 64 leaves 16 GB for macOS, the browser, and ComfyUI's CPU-side
  tensors, which the torch watermark does not count. Big Flux2 and Wan
  jobs fit.
- Legit job OOMs at 48: raise to 52 (Metal's own recommendation) and accept
  the thinner margin. Above 52 is past what Apple considers safe and the
  incident comes back.
- Mac still stalls at 48: the culprit is CPU-side memory, not GPU. Lower
  the budget (40 to prove the wall, then tune up) or add `--cache-none` by
  editing the launcher; `COMFYUI_CACHE_LRU=0` gets most of the way.
- Pin a value per machine in the plist's `EnvironmentVariables`, or export
  it in the shell for a one-off run.

## Install (once per machine)

- Quit Comfy Desktop and turn off its launch-at-login. Optionally set
  `Comfy-Desktop.AutoUpdate` to false in
  `<base>/user/default/comfy.settings.json` so the source checkout stops
  moving under the launcher.
- `bin/tds-install -S` registers the unit when it is listed under
  `SERVICES`; until then, by hand:

```
cp macos/launchd/com.tds.comfyui.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.tds.comfyui.plist
```

- The plist runs the bare `launch-comfyui`; `.zshenv` puts the tiered
  `tds_bin` on PATH, so the script must be in a released or installed
  tier, not only in a topic worktree.

## Run

- Start: `launchctl kickstart -k gui/$UID/com.tds.comfyui`
- Stop: `launchctl stop gui/$UID/com.tds.comfyui`
- Status: `launchctl print gui/$UID/com.tds.comfyui | grep -E 'state|pid'`
- UI: `http://127.0.0.1:8188` in any browser. Port 8188 is ComfyUI's
  default; Comfy Desktop uses 8000, so both can coexist while migrating.
- By hand, no launchd: `launch-comfyui` in a terminal (logs to the tty), or
  `launch-comfyui --dry-run` to see the derived numbers and argv without
  starting anything.

## Logs

- Launcher and torch output: `~/Library/Logs/comfyui-launchd/comfyui.log`
  (the launcher owns this path; launchd cannot expand `~`).
- ComfyUI's own log: `<base>/user/comfyui.log`.
- Evidence of the cap working: a `torch.OutOfMemoryError` / `MPS backend
  out of memory` traceback in the log, then launchd restarts an empty
  server within 30 s, and the Mac never stalled.

## Uninstall

```
launchctl bootout gui/$UID/com.tds.comfyui
rm ~/Library/LaunchAgents/com.tds.comfyui.plist
```

## Fallback: a macOS VM

- If in-process caps cannot hold a workload, a macOS guest under
  Virtualization.framework (Tart) gives a fixed RAM wall and paravirtual
  Metal. Slower, and PyTorch MPS inside a guest is not guaranteed; prove
  MPS works in the guest before moving the 141 GB model tree.
