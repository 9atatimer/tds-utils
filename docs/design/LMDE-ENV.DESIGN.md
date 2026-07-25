# LMDE Shell Environment Propagation

> **Status:** ADOPTED  
> **Date:** 2026-07-24  
> **Authors:** Antigravity (from design discussion with Todd)  
> **Depends on:** [PROVISION.DESIGN.md](./PROVISION.DESIGN.md)

---

## Overview

A fundamental divide exists between traditional CLI tools (like `gemini-cli`) and modern, GUI-integrated coding agents (like Antigravity, OpenCode, or IDE extensions). 

When a user runs a CLI tool in their terminal, it inherits a fully interactive, login shell environment. Its `$PATH` is fully hydrated by `.zprofile` and `.zshrc`. 

When a GUI application spawns a background agent or executes a terminal command (e.g., `zsh -c "git push"`), it typically launches a **non-interactive, non-login shell**. According to `zsh` startup sequence rules, **only `~/.zshenv` is sourced**. Files like `.zprofile` and `.zshrc` are completely bypassed.

As a result, agents running under GUI applications (like Antigravity) inherit a barren, sparse `launchd` environment. They frequently crash when attempting to invoke user-installed tools (`npm`, `gh`, `gadmin`, `uv`, etc.) because those tools exist in directories (`/opt/homebrew/bin`, `~/.local/bin`) that were never appended to the `$PATH`.

## The Solution

To provide a consistent "Language Model Development Environment" (LMDE) regardless of how the agent is executed, all pure environment configurations must be migrated into `.zshenv`.

### Architecture Policy

1. **`.zshenv` (Universal Environment):** 
   Must contain all `export PATH=...` statements, `brew shellenv` evaluations, and non-interactive environment variables (e.g., `NVM_DIR`, `PYENV_ROOT`, `SSH_AUTH_SOCK`). This ensures background shells spawned by any LMDE agent receive the exact same toolchain visibility as a human terminal.
   
2. **`.zprofile` (Login Setup):**
   Should be reserved for tasks that truly only need to run once per login session (e.g., starting ssh-agent). It should no longer be used for `PATH` construction.

3. **`.zshrc` (Interactive Only):**
   Must be strictly reserved for interactive tools: aliases, functions, `PROMPT` styling, auto-completions (`compinit`), and history settings. No critical environment variables should be trapped here.

## Impact

By adopting this structure, the "crippled PATH" malady is cured at the OS level. Agents no longer require contortions like absolute paths or custom hook injections to discover the user's tools; they simply inherit the correctly assembled environment universally.
