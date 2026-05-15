# Claude jj and Spoke

**Give Claude Code on the Web a [`jj` (Jujutsu)](https://jj-vcs.github.io/jj/)
VCS layer on top of authenticated GitHub access — without `gh` and without
GitHub PR creation.**

A sibling of [`claude-github-and-spoke`](https://github.com/oaustegard/claude-github-and-spoke)
(the `gh` + GitHub-PR-flavored hub) and
[`claude-tangled-spoke`](https://github.com/oaustegard/claude-tangled-spoke)
(the Tangled / ATProto hub).

## What this gives you

After session start, your CCotw session has:

- **`jj` v0.41** on `$PATH`, identity configured from your GitHub PAT
- **Git credential helper** wired for `github.com` HTTPS, so
  `jj git clone` and `jj git push` work against private repos with no
  token-in-URL leakage
- **MCP GitHub server denied** — that server only sees the hub repo and
  duplicates a `jj`-shaped workflow anyway

## Why jj-native means PR-free

`gh pr create` is convenient but it's a one-way door away from `jj`.
This hub keeps the loop tight:

```
jj git push --bookmark X
↓
https://github.com/owner/repo/compare/main...X
↓
human reviews + merges in the web UI
```

Reviews still happen in GitHub — they just happen at the compare-URL
hand-off, not at a CLI-created PR record. If you want `gh pr create`
flow, use [`claude-github-and-spoke`](https://github.com/oaustegard/claude-github-and-spoke)
instead.

## The hub/spoke model

- **Hub** (this repo): boots the session, installs `jj`, configures identity
- **Spokes** (your GitHub repos): cloned under `./.spokes/<name>`, where work happens

```bash
jj git clone https://github.com/owner/repo .spokes/repo
cd .spokes/repo
jj new main                                  # new change on main
# … edit …
jj describe -m "fix: handle empty input"
jj bookmark create feature-x -r @            # bookmark the working copy (@)
jj git push --bookmark feature-x
echo "Review: https://github.com/owner/repo/compare/main...feature-x"
```

## Quick start

1. **Use this template.** Click the green "Use this template → Create
   a new repository" button at the top of
   [github.com/oaustegard/claude-jj-and-spoke](https://github.com/oaustegard/claude-jj-and-spoke).
2. Create a `.env` file (gitignored) with your GitHub PAT:
   ```
   GH_TOKEN=ghp_your_token_here
   ```
   The PAT needs `repo` scope for spoke access. Optional:
   `JJ_USER_NAME` / `JJ_USER_EMAIL` to override the identity (otherwise
   it's pulled from `GET /user` with the PAT).
3. Open **your** new repo in Claude Code on the Web.
4. The `SessionStart` hook runs `boot.sh` automatically.

## What's in the box

| File | Purpose |
|------|---------|
| `boot.sh` | Installs `jj` from upstream tarball, writes `~/.config/jj/config.toml`, sets up the git credential helper |
| `.claude/settings.json` | SessionStart hook + denies MCP GitHub server |
| `CLAUDE.md` | Agent-facing instructions — recipes, gotchas, the PR-free hand-off |
| `skills/jj/SKILL.md` | jj mental model, command reference, recovery primitives |

## Coverage (this PR)

| Capability | Status |
|------------|--------|
| `jj git clone` / `push` / `fetch` for GitHub spokes | ✓ |
| Identity from `$GH_TOKEN` or `$JJ_USER_*` | ✓ |
| Commit signing (`/tmp/code-sign` cwd-walk) works for `.spokes/<name>` paths | ✓ |
| `jj op log` / `jj op restore` for undo | ✓ |
| `ghi` CLI for GitHub issues | ✗ — lands in [#2](https://github.com/oaustegard/claude-jj-and-spoke/issues/2) |
| GitHub PR creation | ✗ — out of scope (use compare URLs, or see `claude-github-and-spoke`) |
| GitHub PR review/merge | ✗ — out of scope (web UI) |

## Auth security notes

- `.env` is gitignored. Never commit it.
- The credential helper is wired with a `!f() { ... }; f` inline shell
  function that reads `$GH_TOKEN` from process env. The token never
  appears in `.git/config`, on stdout, or in URLs.
- If you accidentally leak the PAT (any variant of
  `https://x-access-token:${GH_TOKEN}@...`), rotate it immediately at
  https://github.com/settings/tokens.

## Background

This is the third sibling in a series of CCotw hub templates that pair
the boot/configure shape with a single forge + VCS combination:

- [`claude-github-and-spoke`](https://github.com/oaustegard/claude-github-and-spoke)
  — GitHub forge, `git` VCS, `gh` CLI, GitHub PRs
- [`claude-tangled-spoke`](https://github.com/oaustegard/claude-tangled-spoke)
  — Tangled forge, `git` VCS, `tg` CLI, patch-based PRs over ATProto
- **`claude-jj-and-spoke`** (this repo) — GitHub forge, `jj` VCS, no PR
  CLI by design, compare-URL hand-off

The container-layer caching story is the same across all three; see the
[Container Layer Hack](https://austegard.com/blog/custom-container-layers-for-claudes-ephemeral-machines.html)
post for the full background.

## License

MIT
