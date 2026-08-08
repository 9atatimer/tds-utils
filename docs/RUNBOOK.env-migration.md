# RUNBOOK: env-distribution migration and seeding

Human-executed procedures for issue #202 / ENV-DISTRIBUTION. Agents must
not run these: they rewrite the live configuration of a real machine.

## A. Home machine: cut the live $HOME links over to current/

Today ~14 $HOME symlinks point into the working checkout, so branch
switches rewrite live shell config. After this procedure they point at
`~/.tds/dist/current/...` and only `tds-install` changes live config.

Preconditions: this branch merged to master; primary checkout on master
and clean; `tds-internal` checked out beside it with
`manifests/home.manifest` present.

```zsh
cd ~/workplace/tds-utils && git pull origin master
bin/tds-export -m ../tds-internal/manifests/home.manifest -o ~/.tds/artifacts
bin/tds-install -a ~/.tds/artifacts/tds-env-home-*.tar.gz
```

That single install run is the flip: it stages the version, runs every
package's VERIFY (abort = nothing changed), atomically flips
`~/.tds/dist/current`, and repoints each existing checkout-targeting
symlink at `current/...` (one rename(2) per link; regular files are
never clobbered).

Verify:

```zsh
for l in .zshenv .zprofile .zshrc .alias .gitconfig .gitignore_global \
         .tmux.conf .emacs.d .screenrc clai.d; do
    printf '%-20s -> %s\n' "~/$l" "$(readlink ~/$l)"
done
# every target should start with ~/.tds/dist/current/
exec zsh -l        # fresh shell: prompt, aliases, PATH sanity
command -v tds-export tds-install   # current/bin now owns PATH
```

Rollback (any time, one command): `tds-install --rollback`.
Catastrophic bail-out (installer itself broken): relink by hand at the
old targets, e.g. `ln -sfh ~/workplace/tds-utils/macos/dot.zshenv ~/.zshenv`
for each link in the table in AGENT.md.

Notes:
- `dot.zshenv` now prefers `~/.tds/dist/current/bin` and only falls back
  to the checkout's `bin/` when no install exists, so the PATH cutover is
  automatic and reversible by removing `~/.tds/dist`.
- SERVICES (launchd/systemd units) register only with `tds-install -S`.
- Re-seeding one package later: `tds-export -m ... -p emacs` then
  `tds-install -a <artifact>` -- the partial artifact merges over current
  into a new version, so nothing is orphaned.

## B. Work MacBook: day-0 seeding

Prereqs on the work machine, via work-approved channels only:
`brew install gnupg uv emacs` (plus whatever the chosen manifest needs).
The work gpg identity must exist first -- enrollment procedure and the
work manifest live in tds-internal (private).

At home, publish the encrypted artifact:

```zsh
bin/tds-export -m ../tds-internal/manifests/work.manifest -r
```

On the work machine:

```zsh
curl -LO https://github.com/9atatimer/tds-utils/releases/download/env-<ver>/<slug asset>.tar.gz.gpg
gpg --decrypt <slug asset>.tar.gz.gpg > tds-env.tar.gz   # verifies the authoring signature
tar -xzf tds-env.tar.gz && cd tds-env-*
./install.sh
git clone <work-private-overlay-repo> ~/.tds-local        # optional, device-owned
```

Steady state: no tds repo on work hardware, no remotes to the personal
tree; `~/.tds/dist/current` is the environment; work-authored config
lives in `~/.tds-local` (its own work-private repo). Updating is a fresh
`-r` export at home, then download + decrypt + `./install.sh` again;
`tds-install --rollback` undoes a bad version.
