#!/usr/bin/env bash
# SessionStart hook: install the latest PUBLISHED ast-mcp release into a
# project-local dir so the project .mcp.json can launch it. No global install
# (AGENT.md: prefer local dependencies) and no local build — always the
# released tarball attached to the newest `ast-mcp-v*` GitHub Release.
#
# Synchronous on purpose: it must finish before Claude Code loads .mcp.json and
# spawns the server. Best-effort — if the release can't be fetched (no token /
# egress), it logs and exits 0 so the session still starts (ast-mcp just won't
# be available until access is configured).
#
# This is a VENDORED COPY of the canonical script, which lives at
# .claude/hooks/session-start.sh in 9atatimer/ai-tools (packages/ast-mcp is
# where ast-mcp is built and released -- see RELEASE.md and RUNBOOK.md there
# for the full context this header summarizes). Fixes land in ai-tools first,
# then get synced here as a deliberate, reviewed copy -- NOT fetched at
# session-start time from that repo: a hook that downloads and executes
# another repo's script on every session, unpinned, is its own supply-chain
# risk (whoever can push to that repo's default branch gets code execution
# here, with no review gate on this side) -- the same category of problem
# ai-tools issue #72 rejected for the cached binary, just relocated to the
# script layer. If you're editing this file, edit the canonical copy in
# ai-tools first and re-sync, don't let this repo's copy drift ahead.
# One deliberate tds-utils-local addition on top of the vendored ast-mcp
# logic: the clai-provision branch at the top of main() is part of the
# issue #84 universal-provisioning rollout (see docs/design/PROVISION.DESIGN.md
# and sandbox/ in this repo), not part of the canonical ai-tools copy.
#
# Every release cut with the CURRENT release workflow
# (.github/workflows/release-ast-mcp.yml in ai-tools) ships a paired
# `.sha256` checksum asset -- releases cut before that workflow existed do
# not (see the newest-first fallback in fetch_tarball below, which skips
# those). This hook downloads both the tarball and its checksum and verifies
# before installing. ai-tools deliberately rejected the cached
# env-setup-script delivery model (see issue #72 there) because a stale
# cached binary could keep serving a known-vulnerable build for up to ~7 days
# (the environment snapshot's cache window) with no way to force an early
# refresh; running this hook fresh every session -- and verifying the
# artifact each time -- is the mitigation. Do not remove the verification
# step, and do not add a caching layer in front of the fetch.
# No -e: deliberately fail-open at the STEP level, not the script level.
# fetch_tarball/install_verified return 1 on any failure and main() catches
# that with `if ! fetch_tarball || ! install_verified`, logs why, cleans up,
# and always exits 0 -- a broken release/network must never abort this hook
# uncaught and block the agent session from starting. Under -e, a single
# unguarded failing command (this script has several, e.g. bare `mkdir -p`)
# would kill the script before that catch-and-report logic ever runs. If you
# add new top-level (non-function-body) commands, keep them guarded the same
# way -- don't add -e as a shortcut.
set -uo pipefail

# --- Action/flow functions ---
# (REPO/INSTALL_DIR/TMP are set inside main() below, per the function-based
# shell-script convention this hook's consumers use (AGENT.md in this repo;
# CLAUDE.md in consumer repos like tds-utils) -- no loose top-level logic
# outside a main block. Everything from here down to main() is a function
# DEFINITION, not executed logic, so it's fine to sit at top level.)
note() { echo "[ast-mcp hook] $*" >&2; }

# sha256_of <file> -- portable sha256 (Linux sha256sum / macOS shasum).
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    return 1
  fi
}

fetch_tarball() {
  # Prefer gh if present and authenticated. Newest-first, but a release is
  # only usable if it has BOTH a tarball and a checksum asset (older releases
  # cut before this repo started publishing checksums do not) -- fall back to
  # progressively older releases rather than failing on the newest one alone.
  if command -v gh >/dev/null 2>&1; then
    local tags tag
    tags="$(gh release list --repo "$REPO" --limit 50 --json tagName \
           --jq '.[].tagName | select(startswith("ast-mcp-v"))' 2>/dev/null)"
    if [ -n "${tags:-}" ]; then
      while IFS= read -r tag; do
        [ -n "$tag" ] || continue
        rm -f "$TMP"/*.tgz "$TMP"/*.tgz.sha256 2>/dev/null
        if gh release download "$tag" --repo "$REPO" \
             --pattern '*.tgz' --pattern '*.tgz.sha256' --dir "$TMP" 2>/dev/null \
           && ls "$TMP"/*.tgz >/dev/null 2>&1 && ls "$TMP"/*.tgz.sha256 >/dev/null 2>&1; then
          note "downloaded $tag (tarball + checksum) via gh"; return 0
        fi
      done <<< "$tags"
      # Distinguishable from "gh/auth/network unusable" below: releases DO
      # exist, we just couldn't find one with a checksum asset yet -- likely
      # rollout lag right after this checksum requirement shipped, not a
      # config problem. Say so explicitly rather than falling through to a
      # generic token/egress message that sends someone debugging the wrong thing.
      note "found $(printf '%s\n' "$tags" | grep -c .) ast-mcp-v* release(s) via gh, but none has both a .tgz and .tgz.sha256 asset yet -- cut a new ast-mcp-v* release with the current release-ast-mcp.yml workflow"
    fi
    rm -f "$TMP"/*.tgz "$TMP"/*.tgz.sha256 2>/dev/null
  fi
  # Fallback: REST API with a PAT (Contents:read on the private repo).
  # MUST be GH_AI_TOOLS_PAT: the GH_TOKEN injected in Claude Code web sandboxes
  # is the brokered GitHub-App token, which 401s against api.github.com directly
  # (and that name is used by other tools). Supply a dedicated fine-grained PAT.
  local token="${GH_AI_TOOLS_PAT:-}"
  [ -n "$token" ] || return 1
  local api
  api="$(curl -fsSL -H "Authorization: Bearer $token" \
         "https://api.github.com/repos/$REPO/releases?per_page=50" 2>/dev/null)" || return 1
  # Newest-first ast-mcp-v* release that has BOTH a .tgz and a matching
  # .tgz.sha256 asset -- same fallback reasoning as the gh path above.
  local urls
  urls="$(printf '%s' "$api" | node -e '
    let s=""; process.stdin.on("data",d=>s+=d).on("end",()=>{
      const releases=JSON.parse(s).filter(x=>x.tag_name?.startsWith("ast-mcp-v"));
      let found=false;
      for (const rel of releases) {
        const assets=rel.assets||[];
        const tgz=assets.find(a=>a.name.endsWith(".tgz"));
        // Tie the checksum asset to THIS tarball by exact name (tgz.name +
        // ".sha256"), not independently -- a release with more than one
        // tarball/checksum pair could otherwise mix a tarball from one pair
        // with a checksum from another.
        const sum=tgz && assets.find(a=>a.name===tgz.name+".sha256");
        if (tgz && sum) { process.stdout.write(tgz.url+"\n"+sum.url); found=true; break; }
      }
      // Same rollout-vs-config distinction as the gh path above: say
      // explicitly when releases exist but none has a checksum asset yet,
      // so this does not read as a token/egress problem during rollout.
      // Written to stderr (this node call is NOT stderr-redirected below),
      // stdout stays clean for $urls.
      if (!found && releases.length) {
        process.stderr.write("[ast-mcp hook] found "+releases.length+" ast-mcp-v* release(s) via REST, but none has both a .tgz and .tgz.sha256 asset yet -- cut a new ast-mcp-v* release with the current release-ast-mcp.yml workflow\n");
      }
    });')"
  [ -n "${urls:-}" ] || return 1
  local tgz_url sum_url
  tgz_url="$(echo "$urls" | sed -n 1p)"
  sum_url="$(echo "$urls" | sed -n 2p)"
  curl -fsSL -H "Authorization: Bearer $token" -H "Accept: application/octet-stream" \
       "$tgz_url" -o "$TMP/ast-mcp.tgz" 2>/dev/null \
    && curl -fsSL -H "Authorization: Bearer $token" -H "Accept: application/octet-stream" \
       "$sum_url" -o "$TMP/ast-mcp.tgz.sha256" 2>/dev/null \
    && { note "downloaded latest release (tarball + checksum) via REST API"; return 0; }
  return 1
}

# resolve_tarball -- print the path of exactly one downloaded tarball, or fail.
# Fetching could in principle leave more than one *.tgz in $TMP (an unexpected
# extra release asset, a future pattern change); installing via a glob in that
# case could silently install a DIFFERENT file than the one just verified.
# Fail closed rather than guess.
resolve_tarball() {
  local matches=() f
  for f in "$TMP"/*.tgz; do
    [ -e "$f" ] && matches+=("$f")
  done
  case "${#matches[@]}" in
    1) printf '%s\n' "${matches[0]}" ;;
    0) note "no tarball downloaded"; return 1 ;;
    *) note "expected exactly one tarball, found ${#matches[@]}; refusing to guess which to install"; return 1 ;;
  esac
}

# verify_checksum <tgz> -- refuse to install unless the exact tarball path
# passed in hashes to the value in its paired <tgz>.sha256. A missing checksum
# asset, a missing sha256sum/shasum binary, or a mismatch are all treated as
# failure (fail closed, not open) -- see the header comment for why this exists.
verify_checksum() {
  local tgz="$1" sum expected actual
  sum="${tgz}.sha256"
  if [ ! -f "$sum" ]; then
    note "checksum asset missing ($sum); refusing to install unverified artifact"
    return 1
  fi
  expected="$(awk '{print $1}' "$sum")"
  actual="$(sha256_of "$tgz")" || { note "no sha256sum/shasum on PATH; cannot verify, refusing to install"; return 1; }
  if [ "$expected" != "$actual" ]; then
    note "CHECKSUM MISMATCH: expected $expected, got $actual -- refusing to install"
    return 1
  fi
  note "checksum verified ($actual)"
}

# install_verified -- resolve, verify, and install the SAME tarball path
# throughout (no re-globbing between verify and install).
install_verified() {
  local tgz
  tgz="$(resolve_tarball)" || return 1
  verify_checksum "$tgz" || return 1
  mkdir -p "$INSTALL_DIR"
  # Local install (NOT -g): the tarball lands in $INSTALL_DIR/node_modules; the
  # project .mcp.json launches it from there. Idempotent across sessions.
  if ! npm install --prefix "$INSTALL_DIR" "$tgz" >/dev/null 2>&1; then
    note "npm install failed (missing npm / network / build error) — ast-mcp unavailable this session"
    return 1
  fi
  # A "successful" npm install doesn't guarantee the entrypoint .mcp.json
  # actually launches exists (malformed tarball, unexpected package layout).
  # Check it explicitly so a bad install fails closed -- same policy as the
  # checksum check above -- rather than reporting success while leaving
  # .mcp.json pointed at a file that isn't there.
  #
  # Check the npm-installed BIN SHIM (node_modules/.bin/ast-mcp), not the
  # package's internal dist/index.js -- the package.json "bin" field is the
  # published, stable contract; the dist/ layout underneath it is an
  # implementation detail that could change on a future ast-mcp release
  # without the bin path changing. .mcp.json launches via this same bin
  # shim, so this check verifies the exact thing that gets executed.
  local entry="$INSTALL_DIR/node_modules/.bin/ast-mcp"
  if [ ! -x "$entry" ]; then
    note "npm install reported success but $entry is missing or not executable — treating as failed install"
    return 1
  fi
  note "installed published ast-mcp into $INSTALL_DIR (local, not global)"
}

# --- Main ---

main() {
  # clai provision (issue #84): when clai is already on PATH (laptop, or a
  # sandbox whose setup script bootstrapped it), run the idempotent
  # provisioning engine before anything else -- fast no-op when current,
  # --offline-ok so no-network sessions degrade with a warning instead of
  # noise. Non-fatal by design; then fall through to the existing
  # remote-gated ast-mcp flow (locally the script exits at the gate below,
  # as before).
  if command -v clai >/dev/null 2>&1; then
    note "clai found on PATH -- running clai provision (issue #84)"
    clai provision --offline-ok || note "clai provision failed (non-fatal)"
  fi

  [ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

  REPO="9atatimer/ai-tools"
  INSTALL_DIR="${CLAUDE_PROJECT_DIR:-$PWD}/.ast-mcp"   # gitignored, project-local
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT                            # never leave artifacts in /tmp

  if ! fetch_tarball || ! install_verified; then
    note "could not fetch+verify the published release (need gh, or GH_AI_TOOLS_PAT with Contents:read, plus egress to api.github.com + *.githubusercontent.com + registry.npmjs.org). ast-mcp will be unavailable this session."
    # .mcp.json unconditionally points at $INSTALL_DIR's entrypoint. If a
    # PREVIOUS session's successful install is still sitting there (this session
    # resumed the same container rather than starting fresh), leaving it in
    # place would let Claude Code launch that old copy despite this session
    # being unable to confirm it's still the current, verified release --
    # exactly the "stale binary nobody re-checked" failure mode ai-tools
    # issue #72 rejected the cached env-setup-script model over. Remove it so a failed
    # verification actually means "unavailable," not "silently serve whatever
    # was here before."
    #
    # Guard the rm -rf: INSTALL_DIR is built from an env var + $PWD, so refuse
    # to touch anything that isn't unambiguously "some path ending in our own
    # .ast-mcp directory" before deleting -- cheap insurance against ever
    # widening this to a catastrophic delete if CLAUDE_PROJECT_DIR/PWD is ever
    # empty or unexpected.
    case "$INSTALL_DIR" in
      /.ast-mcp|"") note "refusing to rm -rf suspicious INSTALL_DIR ($INSTALL_DIR)" ;;
      */.ast-mcp) rm -rf "$INSTALL_DIR" ;;
      *) note "refusing to rm -rf INSTALL_DIR, doesn't end in /.ast-mcp: $INSTALL_DIR" ;;
    esac
  fi
  exit 0
}

main "$@"
