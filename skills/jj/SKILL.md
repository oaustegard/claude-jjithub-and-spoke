---
name: jj
description: |
  Use this skill when the user asks about `jj` (Jujutsu) or any operation
  on a git repo where they want jj semantics — clones, commits, bookmarks,
  rebases, conflict handling, undo via `op log`. Triggers include:
  "use jj for this", "jj clone …", "make a bookmark", "what does
  `jj describe` do", "rebase this stack with jj", "undo my last jj
  operation". This is the canonical reference for the jj-native workflow
  on this hub.
---

# jj — Jujutsu VCS skill

**This hub is jj-native. We do not use GitHub PRs.** Reviews happen via
compare-URL hand-off to a human:

```bash
jj git push --bookmark feature-x
# → https://github.com/<owner>/<repo>/compare/main...feature-x
```

If you find yourself reaching for `gh pr create` or "let me install
`gh`" — stop. That's the wrong mental model for this hub. PR-flavored
work belongs in `claude-github-and-spoke`.

## Seven-point mental model

Adapted from the upstream
[git comparison doc](https://jj-vcs.github.io/jj/latest/git-comparison/).
Each one is a place git-habits silently mislead.

1. **Working copy is auto-committed.** Every `jj` command snapshots first.
   There is no `jj add`, no equivalent of "untracked changes" anxiety. Save
   the file, run any `jj` command, and the snapshot is captured.

2. **No index.** `git add -p; git commit` becomes `jj split`. To amend the
   parent with current changes: `jj squash` (or `jj squash <file>` for a
   single path, `jj squash -i` for an interactive picker).

3. **No current bookmark — this is the biggest git-habit trap.**
   `jj describe` and `jj new` do not advance any bookmark. Bookmarks
   (jj's term for branches) must be explicitly moved with
   `jj bookmark create <name> -r @` (new) or
   `jj bookmark set <name> -r @` (move existing) before `jj git push`.
   The `-r @` (working copy) vs `-r @-` (parent) choice trips git brains;
   for "the change I just described and want to push", `-r @` is correct.

4. **Conflicts commit.** `jj rebase` / `jj merge` never fail on conflict;
   conflicts get recorded into the commit and resolved later with
   `jj resolve`. Don't treat exit code 0 as "merge succeeded" — check
   `jj log` for a `conflict` marker on the commit.

5. **Descendants auto-rebase.** `jj rebase -r X -d Y` propagates to X's
   children automatically. No manual fix-up of stacked commits.

6. **Bookmarks travel by name across remotes.** `jj git push --bookmark main`
   is the whole story; no `origin main:main` ceremony, no upstream-tracking
   dance.

7. **`jj op log` + `jj op restore <id>` undoes anything.** Replaces
   `git reflog`. Every jj operation (including `git push`, `bookmark
   create`, rebase, even pulls) gets a unique op ID. To roll back:

   ```bash
   jj op log                                # find the op to restore to
   jj op restore <op-id-prefix>             # restore that state
   ```

   This is the agent-recovery primitive that earns jj its keep. If
   something goes sideways, the path back is always one command away.

## Common verbs (cheatsheet)

```bash
# Reading state
jj log                                       # default-command, configured at boot
jj log -r 'all()'                            # everything, including remote bookmarks
jj show                                      # working copy diff vs. parent
jj diff -r @                                 # alias
jj op log                                    # operation history
jj bookmark list -a                          # local + remote bookmarks

# Making changes
jj new <rev>                                 # start a new change on top of <rev>
jj describe -m "msg"                         # set the current change's message
jj squash                                    # fold @ into @- (amend parent)
jj squash --from <rev> --into <rev>          # arbitrary move
jj split                                     # interactively split @ into multiple commits
jj abandon                                   # drop @, move cursor to parent

# Bookmarks (= branches)
jj bookmark create feature-x -r @            # new bookmark at working copy
jj bookmark set feature-x -r @               # move existing
jj bookmark delete feature-x                 # locally
jj bookmark forget feature-x                 # also forget remote tracking

# Talking to git remotes
jj git clone https://github.com/owner/repo .spokes/repo
jj git fetch                                 # update all remote bookmarks
jj git push --bookmark feature-x             # push one bookmark
jj git push                                  # push all locally-modified tracked bookmarks
jj git push --deleted                        # push all locally-deleted bookmarks
                                              # (separate form — NOT --bookmark + --deleted)

# Rebasing / reorganizing
jj rebase -r X -d Y                          # move X (and descendants) onto Y
jj rebase -s X -d Y                          # move X and its subtree onto Y
jj resolve                                   # work through conflicted files

# Undo
jj op log
jj op restore <id-prefix>
jj undo                                      # alias for restoring the previous op
```

## End-to-end recipes

### Clone and ship a change

```bash
jj git clone https://github.com/owner/repo .spokes/repo
cd .spokes/repo
jj new main                                  # change on main
$EDITOR src/thing.py
jj describe -m "fix: handle empty input in thing()"
jj bookmark create feature-x -r @
jj git push --bookmark feature-x
echo "Review: https://github.com/owner/repo/compare/main...feature-x"
```

### Stack a second change on top

```bash
jj new                                       # child of current @ (= feature-x tip)
$EDITOR src/other.py
jj describe -m "test: cover the empty-input path"
jj bookmark set feature-x -r @               # advance the bookmark
jj git push --bookmark feature-x
```

### Split a commit you already made

```bash
jj log -r feature-x                          # find the commit to split
jj edit <commit-id>                          # check it out as working copy
jj split                                     # interactive: stage chunks into commit 1, rest into commit 2
jj bookmark set feature-x -r @               # bookmark moves to the second piece
```

### Squash a fix into the previous commit

```bash
$EDITOR src/thing.py                         # add the fix
jj squash                                    # fold @ into @-
                                              # (or `jj squash --into <id>` for any ancestor)
```

### Resolve a conflict

```bash
jj rebase -r feature-x -d main               # may record a conflict
jj log                                       # check for `conflict` marker
jj resolve                                   # opens conflicted files in $EDITOR
jj squash                                    # if you want the resolution folded into the original commit
```

### Undo the last push

```bash
jj op log --limit 5                          # find the push op
jj op restore <op-id-prefix-of-the-one-BEFORE-the-push>
# Note: this restores LOCAL state. The remote bookmark still exists.
# To remove the remote: `jj bookmark delete <name>; jj git push --deleted`
# or `git push origin --delete <name>` (colocated repos support both).
```

## Deleting a remote bookmark

`jj git push --deleted` is **its own form** — not a flag combined with
`--bookmark`. Order matters:

```bash
jj bookmark delete feature-x                 # mark deleted locally
jj git push --deleted                        # ship all locally-deleted bookmarks
```

Since the spoke is colocated, plain git also works as a fallback:

```bash
git push origin --delete feature-x
```

## When `jj` doesn't cover something — pointers

- [Git command table](https://jj-vcs.github.io/jj/latest/git-command-table/)
  — side-by-side translation
- [Working with GitHub](https://jj-vcs.github.io/jj/latest/github/)
  — GitHub-specific patterns (force pushes, PR handoff)
- [Bookmarks concept](https://jj-vcs.github.io/jj/latest/bookmarks/)
  — full bookmark semantics
- [Operation log](https://jj-vcs.github.io/jj/latest/operation-log/)
  — recovery and history rewriting
- [Revsets](https://jj-vcs.github.io/jj/latest/revsets/)
  — the language for selecting revisions in `-r` flags

## When to stop and ask

- A `jj git push` would touch a repo the user doesn't own and you have
  no clear instruction to act there. The compare URL is a soft commit;
  the bookmark on the remote is harder to retract.
- `jj op log` shows operations from before this session that you don't
  recognize — surface them before continuing.
- A rebase records conflicts you can't tell how to resolve from the
  surrounding context — show `jj resolve --list` output and ask.
- You're about to run `jj abandon` on a commit that has descendants on
  bookmarks you didn't create — confirm first.

## Gotchas (diagnosed during this hub's bring-up)

- `jj git push --bookmark X --deleted` is **rejected** by jj's argument
  parser. Use the two-step `jj bookmark delete X; jj git push --deleted`.
- `--colocate` on `jj git clone` is now the **default** in v0.41+; the
  flag still exists for compat but has no effect. Don't sweat including
  it.
- The auto-snapshot means an unsaved-buffer mistake gets captured. If
  you snapshot bad content into `@`, the fix is either edit-and-resnapshot
  or `jj abandon` + `jj new`.
