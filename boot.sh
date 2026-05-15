#!/bin/bash
# Boot hook for Claude Code on the Web.
# Installs the `jj` (Jujutsu) static binary, seeds an identity from $GH_TOKEN,
# and wires a credential helper that lets HTTPS clones/pushes against GitHub
# work without exposing the token in URLs.
#
# This hub is intentionally jj-native at the VCS layer — there is no `gh`
# install here. Issue ops are handled separately by the bundled stdlib
# `ghi` CLI (see `bin/ghi` + `skills/ghi/SKILL.md`). PR creation is not
# part of the flow; reviews hand off to a human via compare URLs (see
# CLAUDE.md).
#
# Required env (from .env, gitignored):
#   GH_TOKEN          — GitHub PAT used for /user lookup and git auth helper
#
# Optional env:
#   JJ_USER_NAME      — override the name written to ~/.config/jj/config.toml
#   JJ_USER_EMAIL     — override the email written to ~/.config/jj/config.toml

set -e

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
JJ_VER="0.41.0"
SUMMARY_LINES=()
summary() { SUMMARY_LINES+=("$1"); }

# ── Source credentials ──
for envfile in "$PROJECT_DIR"/.env "$PROJECT_DIR"/*.env /mnt/project/*.env; do
    [ -f "$envfile" ] || continue
    set -a; . "$envfile" 2>/dev/null || true; set +a
done

# ── Wait for network ──
for i in 1 2 3 4 5; do
    curl -sf --max-time 5 -o /dev/null "https://github.com" && break
    echo "Waiting for network (attempt $i/5)..."
    sleep $((i * 2))
done

# ── Strip legacy git config that breaks HTTPS clones ──
# Past boots (or user dotfiles) sometimes install a global
# `url.git@github.com:.insteadOf=https://github.com/` rule. CCotw blocks port 22,
# so that rewrite turns every HTTPS clone into a failing SSH attempt. Remove it.
git config --global --unset-all url.git@github.com:.insteadof 2>/dev/null || true

# ── Install jj ──
if ! command -v jj >/dev/null 2>&1; then
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  JJ_TRIPLE="x86_64-unknown-linux-musl" ;;
        aarch64) JJ_TRIPLE="aarch64-unknown-linux-musl" ;;
        *) summary "✗ unsupported arch: $ARCH"; ARCH=""; ;;
    esac
    if [ -n "$ARCH" ]; then
        URL="https://github.com/jj-vcs/jj/releases/download/v${JJ_VER}/jj-v${JJ_VER}-${JJ_TRIPLE}.tar.gz"
        TMP=$(mktemp -d)
        if curl -fsSL "$URL" | tar -xz -C "$TMP" 2>/dev/null && [ -x "$TMP/jj" ]; then
            install -m 0755 "$TMP/jj" /usr/local/bin/jj 2>/dev/null || sudo install -m 0755 "$TMP/jj" /usr/local/bin/jj
            rm -rf "$TMP"
            summary "✓ jj $JJ_VER installed"
        else
            summary "✗ jj download/extract failed from $URL"
        fi
    fi
else
    summary "✓ jj already installed ($(jj --version))"
fi

# ── Symlink bundled ghi onto PATH ──
# Stdlib GitHub Issues CLI; PR ops intentionally absent (compare-URL flow).
GHI_BIN="$PROJECT_DIR/bin/ghi"
if [ -x "$GHI_BIN" ]; then
    ln -sf "$GHI_BIN" /usr/local/bin/ghi 2>/dev/null \
        || sudo ln -sf "$GHI_BIN" /usr/local/bin/ghi
    summary "✓ ghi linked from $GHI_BIN"
fi

# ── Configure jj identity ──
# Priority: explicit $JJ_USER_NAME / $JJ_USER_EMAIL > GitHub /user lookup.
JJ_CFG="$HOME/.config/jj/config.toml"
mkdir -p "$(dirname "$JJ_CFG")"

GH_LOGIN=""
if [ -z "${JJ_USER_NAME:-}" ] || [ -z "${JJ_USER_EMAIL:-}" ]; then
    if [ -n "${GH_TOKEN:-}" ]; then
        GH_USER_JSON=$(curl -fsS -H "Authorization: Bearer $GH_TOKEN" \
            -H "User-Agent: claude-jj-spoke-boot" \
            -H "Accept: application/vnd.github+json" \
            https://api.github.com/user 2>/dev/null || echo '')
        if [ -n "$GH_USER_JSON" ]; then
            GH_LOGIN=$(printf '%s' "$GH_USER_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('login') or '')" 2>/dev/null || true)
            if [ -z "${JJ_USER_NAME:-}" ]; then
                JJ_USER_NAME=$(printf '%s' "$GH_USER_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('name') or d.get('login') or '')" 2>/dev/null || true)
            fi
            if [ -z "${JJ_USER_EMAIL:-}" ]; then
                JJ_USER_EMAIL=$(printf '%s' "$GH_USER_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('email') or '')" 2>/dev/null || true)
                if [ -z "$JJ_USER_EMAIL" ] && [ -n "$GH_LOGIN" ]; then
                    JJ_USER_EMAIL="${GH_LOGIN}@users.noreply.github.com"
                fi
            fi
        fi
    fi
fi

JJ_USER_NAME="${JJ_USER_NAME:-jj-user}"
JJ_USER_EMAIL="${JJ_USER_EMAIL:-jj-user@example.invalid}"

cat >"$JJ_CFG" <<EOF
[user]
name = "$JJ_USER_NAME"
email = "$JJ_USER_EMAIL"

[ui]
paginate = "never"
default-command = "log"
EOF

# ── Configure git credential helper for HTTPS clone/push ──
# One-shot helper: keeps $GH_TOKEN in process env, never echoes it to stdout
# or writes it to .git/config. Verified pattern from claude-workspace CLAUDE.md.
if [ -n "${GH_TOKEN:-}" ]; then
    # Clear any prior helpers (idempotent across re-boots), then install ours.
    git config --global --unset-all credential.https://github.com.helper 2>/dev/null || true
    git config --global --add credential.https://github.com.helper \
        '!f() { echo username=x-access-token; echo "password=$GH_TOKEN"; }; f'
    summary "✓ git credential helper configured for github.com"
fi

# ── Sanity probe: ghi auth status ──
# Only when both the token and the binary are present. Parse line 1 of
# `ghi auth status`: "Logged in as <login>" — awk '{print $NF}' yields login.
if [ -n "${GH_TOKEN:-}" ] && command -v ghi >/dev/null 2>&1; then
    GHI_USER=$(ghi auth status 2>/dev/null | head -1 | awk '{print $NF}')
    if [ -n "$GHI_USER" ]; then
        summary "✓ ghi authenticated as $GHI_USER"
    else
        summary "✗ ghi auth failed (check GH_TOKEN)"
    fi
fi

# ── Summary ──
echo "── claude-jj-and-spoke boot ──"
for line in "${SUMMARY_LINES[@]}"; do echo "  $line"; done
JJ_VERSTR=$(jj --version 2>/dev/null | head -1 || echo "jj (missing)")
echo "  ✓ $JJ_VERSTR ready as $JJ_USER_NAME <$JJ_USER_EMAIL>"
echo ""
echo "Try:  jj git clone https://github.com/owner/repo .spokes/repo"
echo "      jj log   |   jj op log   |   jj --help"
echo "      ghi auth status   |   ghi issue list --repo OWNER/NAME"
