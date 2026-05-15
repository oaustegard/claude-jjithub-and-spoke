# Claude jj and Spoke — Agent Instructions

This repo is the **hub**: it boots a Claude Code on the Web session with
[`jj` (Jujutsu)](https://jj-vcs.github.io/jj/) installed and an identity
seeded from the user's GitHub PAT. You work in **spokes** — separate
GitHub repos cloned under `./.spokes/`.

## What you get after boot

- `jj v0.41+` on `$PATH`
- Identity at `~/.config/jj/config.toml` (from `$JJ_USER_*` or `/user` lookup via `$GH_TOKEN`)
- Git credential helper wired for `github.com` HTTPS (clone + push), token never in URLs or `.git/config`
- `ui.paginate = "never"`, `ui.default-command = "log"`

There is **no `gh` CLI** here. This hub is jj-native at the VCS layer.
Issue ops land via a stdlib `ghi` CLI (see issue #2 — not in this
deliverable). Repo-level ops happen through `jj git ...` and direct git
plumbing where needed.

## This hub is PR-free

We do **not** use `gh pr create` or GitHub PR creation from here. The
review hand-off is: push the bookmark, then surface a compare URL.

```bash
jj git push --bookmark feature-x
echo "Review: https://github.com/<owner>/<repo>/compare/main...feature-x"
```

A human reviews and merges in the GitHub web UI. If you find yourself
reaching for `gh pr create` or "let me install `gh` quickly" — stop.
That's the wrong mental model for this hub.

## Spoke clone convention: `./.spokes/<name>` (mandatory)

```bash
jj git clone https://github.com/<owner>/<repo> .spokes/<name>
cd .spokes/<name>
```

`.spokes/` is gitignored. **The clone is colocated automatically** in jj
v0.41+ — both `.jj/` and `.git/` exist alongside each other, so anything
that walks the git tree (signing helpers, git tooling) keeps working.

### Why `.spokes/` specifically

CCotw's container ships `/tmp/code-sign` (wired as
`gpg.ssh.program`) which forwards every commit-signing request to a remote
service that resolves its "source" field from the signer's cwd, and only
recognizes paths inside the hub workspace. Clones placed under `/tmp/` or
`/home/user/` fail signing with:

```
signing server returned status 400: {"error":{"message":"missing source"}}
```

**When does signing fire?** Not on `jj describe` — working-copy snapshots
stay inside `.jj/`. Signing fires when jj exports git objects to `.git/`,
i.e. on `jj git push` (and `jj git export`). The `.spokes/` rule still
applies because that's exactly when you need the signer to succeed.

## MCP GitHub server denied

`.claude/settings.json` denies the built-in GitHub MCP server. It only
sees the hub repo and is GitHub-token-based; we want uniform access to
all GitHub spokes via `jj` + the credential helper instead.

## End-to-end recipe: edit and ship to a spoke

```bash
# 1. Clone the spoke (colocated by default in jj v0.41+)
jj git clone https://github.com/owner/repo .spokes/repo
cd .spokes/repo

# 2. Start a new change on top of main
jj new main

# 3. Edit files. jj auto-snapshots into the working copy on the next command.
$EDITOR src/thing.py

# 4. Describe the change (this names the working copy commit @)
jj describe -m "fix: handle empty input in thing()"

# 5. Create a bookmark pointing at the working copy
#    -r @ is the working copy, where your edits live.
#    -r @- would point at the parent — git-brain trap; don't.
jj bookmark create feature-x -r @

# 6. Push the bookmark — credential helper supplies the token
jj git push --bookmark feature-x

# 7. Hand off to the reviewer
echo "Review: https://github.com/owner/repo/compare/main...feature-x"
```

### Updating an open feature: stack more changes

```bash
# You're on @ already (after step 5 above). Make another change.
jj new                                    # new working-copy child of feature-x tip
$EDITOR src/other.py
jj describe -m "test: cover the empty-input path"
jj bookmark set feature-x -r @            # move the bookmark to the new tip
jj git push --bookmark feature-x
```

### Deleting a remote bookmark

`jj git push --deleted` is its own form — **not** a flag combined with
`--bookmark`. To delete a remote branch:

```bash
jj bookmark delete feature-x              # locally
jj git push --deleted                     # ships all locally-deleted bookmarks
```

Or, since the repo is colocated, plain `git push origin --delete
feature-x` works too.

## Undo: `jj op log` + `jj op restore`

jj records every operation in an operation log. To undo any single op
(or roll back to any earlier state):

```bash
jj op log                                 # list operation history
jj op restore <op-id-prefix>              # restore to that operation
```

This replaces `git reflog` and is the recovery primitive that earns jj
its keep in an agent context — if something goes sideways, the path back
is always one command away.

## Other behaviors worth knowing

- **Auto-snapshot.** Every `jj` command snapshots the working copy first.
  There is no `jj add`. Saving a file is enough.
- **No index.** `git add -p; git commit` → `jj split`. To amend the
  parent with current changes: `jj squash`.
- **Bookmarks don't auto-advance.** `jj describe` and `jj new` do not
  move any bookmark. You move them explicitly with
  `jj bookmark set <name> -r @`. This is the biggest git-habit trap.
- **Conflicts commit.** `jj rebase` / `jj merge` never fail on conflict;
  they record the conflict into the commit. Check `jj log` for conflict
  markers — exit code 0 is not "merge succeeded".
- **Descendants auto-rebase.** `jj rebase -r X -d Y` propagates to
  children automatically. No manual stacked-commit fix-up.

For verbs and concepts not covered here, see
[`skills/jj/SKILL.md`](skills/jj/SKILL.md) (loaded into the session)
and the upstream docs:

- [Git command table](https://jj-vcs.github.io/jj/latest/git-command-table/)
- [Working with GitHub](https://jj-vcs.github.io/jj/latest/github/)
- [Bookmarks concept](https://jj-vcs.github.io/jj/latest/bookmarks/)
- [Operation log](https://jj-vcs.github.io/jj/latest/operation-log/)

## When to stop and ask

- A push would touch a repo the user doesn't own and you have no clear
  instruction to act there.
- `jj op log` shows an operation you don't recognize from this session —
  surface it before continuing.
- The credential helper is unset and a push fails with auth — confirm
  the `.env` setup before retrying.
