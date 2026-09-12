#!/usr/bin/env bash
# infra/coding-agent/open-url.sh
#
# Installed into the image as /usr/local/bin/xdg-open (and pointed at by
# $BROWSER). The image has no browser, no DISPLAY, no Wayland socket and no
# clipboard binary, so when Claude Code wants to open an OAuth login URL it
# calls xdg-open, finds nothing, and can only print the URL -- which then
# wraps across a terminal line, and mouse-selecting a wrapped line drags
# the line breaks in with it. Transcribing an OAuth URL by hand is the
# failure this script exists to remove.
#
# Three deliveries, because each one fails in a different environment and
# no single one is reliable:
#
#   1. A file on /workspace. That is a bind mount, so the host can read it
#      out of the session directory. Works with no terminal support at all.
#   2. OSC 52, straight down the tty. The terminal itself puts the text on
#      the system clipboard -- no X, no Wayland, no clipboard binary, and
#      it crosses the container boundary because it is just bytes on a
#      file descriptor. tmux forwards it outward on its default
#      set-clipboard=external; whether it lands depends on the outer
#      terminal, hence deliveries 1 and 3.
#   3. Printed alone on its own line, so that if it does have to be
#      selected by hand there is nothing else on the line to catch.
set -uo pipefail

url="${1:-}"
if [ -z "$url" ]; then
  echo "xdg-open: no URL given" >&2
  exit 1
fi

# Deliberately not /workspace/<something-tracked>: this is scratch, and
# session.sh's retention check filters this exact name so that capturing a
# URL cannot make a finished session look dirty and block `session.sh clean`.
CAPTURE_FILE="${CLAUDE_URL_CAPTURE_FILE:-/workspace/.claude-auth-url}"

captured=""
if [ -d "$(dirname "$CAPTURE_FILE")" ] && [ -w "$(dirname "$CAPTURE_FILE")" ]; then
  if printf '%s\n' "$url" >> "$CAPTURE_FILE" 2>/dev/null; then
    captured="$CAPTURE_FILE"
  fi
fi

# Write to the terminal directly rather than stdout: the caller is a
# full-screen TUI, and anything on stdout competes with its rendering.
#
# Probe by opening /dev/tty, not with `[ -w ]`. The node image ships the
# device node unconditionally, so the -w test passes even when the process
# has no controlling terminal -- and every write then fails with "No such
# device or address", which swallowed the URL entirely in a container run
# without -t.
out=/dev/stderr
if { : > /dev/tty; } 2>/dev/null; then
  out=/dev/tty
fi

clipboard="no"
if b64="$(printf '%s' "$url" | base64 2>/dev/null | tr -d '\n')" && [ -n "$b64" ]; then
  # OSC 52: ESC ] 52 ; c ; <base64> BEL
  # Only down a real terminal: OSC 52 on stderr would just spray escape
  # bytes into whatever is capturing the log.
  if [ "$out" = /dev/tty ] && printf '\033]52;c;%s\a' "$b64" > "$out" 2>/dev/null; then
    clipboard="attempted"
  fi
fi

{
  echo
  echo "──────────────────────────────────────────────────────────────────"
  echo " No browser in this container. Open this URL yourself:"
  echo
  echo "$url"
  echo
  echo " clipboard (OSC 52): $clipboard"
  [ -n "$captured" ] && echo " also written to:    $captured"
  echo " on the host:        cat <session-dir>/.claude-auth-url"
  echo "──────────────────────────────────────────────────────────────────"
  echo
} > "$out" 2>/dev/null

exit 0
