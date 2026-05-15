---
name: ghi
description: |
  Use this skill when working with GitHub Issues on any spoke from CCotw —
  list, view, create, comment, close, reopen, edit. Triggers include:
  "address issue N", "open an issue", "comment on issue N", "close issue N",
  "list open issues on <repo>", or any github.com/<owner>/<repo>/issues URL.

  Wraps the bundled `ghi` CLI (stdlib-only Python at `bin/ghi`). Auth is
  read from `$GH_TOKEN` — set in `.env`, sourced by `boot.sh`.
---

# ghi — GitHub Issues CLI skill

`boot.sh` symlinks the bundled `bin/ghi` onto `$PATH` and runs a sanity
probe at session start. If `command -v ghi` finds it and `ghi auth status`
reports your login, you're set — no per-skill bootstrap needed.

## Commands

```bash
ghi auth status                                      # whoami + token check

# Reads
ghi issue list  --repo OWNER/NAME [--state open|closed|all]
                [--label X[,Y]] [--author USER] [--limit N] [--json]
ghi issue view  --repo OWNER/NAME N [--json]

# Writes
ghi issue create  --repo OWNER/NAME --title "..." [--body "..."]
                  [--label X[,Y]] [--assignee USER]
ghi issue comment --repo OWNER/NAME N --body "..."
ghi issue close   --repo OWNER/NAME N [--reason completed|not_planned]
ghi issue reopen  --repo OWNER/NAME N
ghi issue edit    --repo OWNER/NAME N [--title ...] [--body ...]
                  [--add-label X[,Y]] [--remove-label X[,Y]]
```

`--body` falls back to stdin, so multi-line bodies are easy:

```bash
cat <<EOF | ghi issue create --repo o/r --title "..."
Long markdown body
with multiple paragraphs.
EOF
```

## Do NOT install `gh`

This hub is intentionally `gh`-free. If `ghi` doesn't expose the surface
you need:

1. **File an issue** on `claude-jj-and-spoke` rather than working around
   with `gh`, raw `curl`, or a one-off Python script.
2. PRs are out of scope here by design — this hub uses jj's compare-URL
   hand-off, not GitHub PR records. See `CLAUDE.md`.

If you find yourself reaching for `apt-get install gh`, `pip install
PyGithub`, or `curl -H 'Authorization: ...' https://api.github.com/...`
— stop. That's the trap this skill exists to prevent.

## Canonical "address issue N" flow

```bash
# 1. Read the issue
ghi issue view --repo OWNER/NAME N

# 2. Clone the spoke under .spokes/, do the work in jj
jj git clone https://github.com/OWNER/NAME .spokes/NAME
cd .spokes/NAME
jj new main
# ... edit ...
jj describe -m "fix: address #N — short summary"
jj bookmark create feature-x -r @
jj git push --bookmark feature-x

# 3. Hand off via compare URL + comment on the issue
ghi issue comment --repo OWNER/NAME N \
  --body "Pushed feature-x. Review: https://github.com/OWNER/NAME/compare/main...feature-x"

# 4. Human reviews + merges + closes. You don't close it.
```

## Output format

Plain text by default: one line per issue for `list` (number, state, title,
author, labels, URL); full body + comments for `view`. `--json` emits raw
GitHub API JSON for piping into `jq`.

`list` filters PRs out of the results — GitHub's `/repos/.../issues`
endpoint returns both, but this is an issue-only tool.

## Auth

`ghi` reads `$GH_TOKEN` on every call. Classic PAT. The token never
appears on stdout or in any saved config.

If a call returns 401: the token is missing, revoked, or expired. Don't
retry blindly — surface the error to the user. The first thing to check
isn't the token itself; it's whether `User-Agent` made it onto the
request. GitHub returns 401 for missing-UA before it returns 401 for a
bad token. `ghi` always sets `User-Agent: ghi/<version>`, so if you're
debugging a 401, it's the token.

## When to stop and ask

- A write op would touch a repo the user doesn't own and you have no
  clear instruction to act there.
- An `issue close` would close an issue you didn't open and the
  resolution isn't obvious from context.
- Repeated 401s after sourcing `.env` — confirm `GH_TOKEN` is set
  correctly, don't shotgun retries.
