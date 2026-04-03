# GitHub Repository Information

This document contains instructions for AI coding agents on how to interact with the GitHub repository.

<!-- Update these when forking the template -->

## Repository Details

-   **Owner:** <!-- your-org -->
-   **Repository:** <!-- your-repo -->
-   **Default Branch:** main

## Push & PR Flow

### Two-Stage PR Workflow

To avoid charging Copilot review cycles to the organization, use this two-stage approach:

**Stage 1: Draft PR to Fork (for AI code review)**
1. Push branch to `origin` (your fork)
2. Create a **Draft PR** targeting `origin/main`
3. Use `[WIP]` prefix in title: `[WIP] feat: add new feature`
4. Copilot reviews happen here — charged to your personal account
5. Address all Copilot feedback

**Stage 2: Final PR to Upstream (for human review and merge)**
1. Once Copilot review is complete, create a new PR from the same branch
2. Target `upstream/main`
3. Remove `[WIP]` prefix — this is the production PR
4. Human reviews and merges
5. Close the Stage 1 draft PR

**Why this matters:** Copilot Pro+ charges are billed to the repository owner. By doing AI review on your fork first, you control the costs.

## Branch Safety (CRITICAL)

- **NEVER WORK ON THE `main` BRANCH**
- **ALWAYS CHECK CURRENT BRANCH FIRST**: Before any git operations, run `git branch --show-current`
- **IF YOU ARE ON MAIN**: STOP IMMEDIATELY. Warn the human. Do NOT proceed.
- **REQUIRED WORKFLOW**: All changes must be made on a feature branch, then merged via Pull Request

## Branch Naming Convention

All branches created by AI agents MUST use a prefix:
- `tstumpf/feat/description` — New features
- `tstumpf/fix/description` — Bug fixes
- `tstumpf/refactor/description` — Refactoring

## Development Workflow

1. **Branch Creation:** Create a feature branch from `main`
2. **Implementation:** Make changes locally
3. **Validation:** Run linter, type checker, tests
4. **Stage & Commit:** Stage verified changes, commit with descriptive message
5. **Push:** Push to origin
6. **PR:** Create PR with clear description

## GitHub Tool Usage

**Prescribed Tool:** `gadmin github`
**Fallback Tool:** `gh` CLI

Use `gadmin github` commands over direct `gh` CLI usage where possible. The `gadmin` wrappers are optimized for token efficiency and context management. The `gh` CLI is available as a fallback when `gadmin` does not cover a specific need.

**Three implementation tiers** (for sandbox compatibility):
- `gadmin github` — bash, requires `gh` CLI (preferred)
- `gadmin github-octokit` — node, requires `octokit` npm package + `GITHUB_TOKEN`
- `gadmin github-gitapi` — node, uses native `fetch()` + `GITHUB_TOKEN` (zero deps)

**GitHub Actions:** Use `gadmin github actions list-runs` to find workflow runs, `gadmin github actions get-job --run <ID> --job <NAME>` to retrieve job outputs. Output is automatically stripped of ANSI codes for token efficiency.

## Automated Review Response

When addressing PR review feedback:

**Step 1: Fetch comments**
- Use `gadmin github pending-comments --repo <OWNER/REPO> --pr <NUMBER>` to list unaddressed comments
- Fallback: `gadmin github pr-comments --repo <OWNER/REPO> --pr <NUMBER>` for all comments
- **IMPORTANT:** The `--repo` flag is required.

**Step 2: Triage — review ALL comments before making changes**
- Read through every comment to understand the full scope
- Decide which you agree with and which you disagree with

**Step 3: Reject comments you disagree with**
- Reply immediately with: `gadmin github reply --repo <OWNER/REPO> --id <ID> --type reject --msg "Reason for disagreement"`

**Step 4: Fix issues you agree with**
- Implement the changes locally
- Commit the fixes (note the SHA)
- **CRITICAL: Push the commit to make it available remotely**

**Step 5: Accept fixed comments with the commit SHA**
- Reply with: `gadmin github reply --repo <OWNER/REPO> --id <ID> --type accept --msg "Agreed, fixed in <sha>"`

**Step 6: Verify all comments addressed**
- Run `gadmin github pending-comments --repo <OWNER/REPO> --pr <NUMBER>`
- Output should be empty (no unaddressed comments)

**Step 7: Consider documentation updates**
- Did an accepted fix reveal a gap worth documenting (new TODO, design change)?
- Did a rejected suggestion surface a lesson worth recording (tool behavior,
  design decision, recurring reviewer misconception)?
- If yes, update relevant docs and include in the next commit. If nothing
  was noteworthy, skip this step.

**Execution notes:**
- Run reply commands **sequentially** (one per tool call) — do NOT batch
- If `gadmin github` fails, fall back to `gadmin github-octokit`, then `gadmin github-gitapi` as last resort
- If you cannot annotate, ask the human for help

## Commit Messages

Use conventional commits:
```
feat: add new feature
fix: correct bug in component
refactor: extract shared logic
test: add unit tests for composable
docs: update architecture doc
```
