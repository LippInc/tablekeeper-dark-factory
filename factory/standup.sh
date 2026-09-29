#!/usr/bin/env bash
# Stand up the factory seats on macOS or Linux: six Band Desktop agents (architect, critic, designer, builder, verifier,
# release clerk; all claude-opus-5-5 by default since 2026-09-26; headless Claude Code runtimes owned by
# Band Desktop), each with its generic mandate as owner instructions, plus the workspace files that keep seat
# work generic; then check the three things the dry runs of 2026-09-23 showed must be true before a task is
# pasted. The POSIX twin of standup.ps1; plain bash 3.2 (stock macOS), no associative arrays.
#
# Phases; each stops the script with a plain reason when its check fails:
#   0. Preconditions: `jam preflight`, and the Claude Code CLI the seats spawn is at least MIN_CLAUDE_VERSION
#      (2.1.280: an older runtime fails the first turn of a claude-opus-5-5 seat with a 400 that shows up only as a
#      room error message; the fix is `claude update`).
#   1. Workspace files: a generic CLAUDE.md and a settings.local.json that disables unrelated plugins.
#   2. Seats, created FRESH under the prefix (default f<mmdd>-<hhmm>; at most 10 characters, because Jam cuts a
#      handle to 24 and the longest seat name is release-clerk) with `jam agent create`, mandates
#      attached with `jam agent instructions set` (live-linked to the mandate files). A seat that already exists is
#      kept only while its worker is running; a stopped worker cannot be started or bound from the CLI, so the script
#      refuses and asks for a new prefix. Every seat must then show `Connected running=true` in `jam list`.
#   3. The room (--room <id>): the human creates it in Band Desktop and adds the seats (a live seat binds on add),
#      or a live seat that is already a member adds them (--add-via <its session scope>); a fresh seat cannot add
#      itself or its set (VERIFIED 2026-09-23). Then it waits until every seat shows a `default-<room id>` session
#      in `jam sessions --as <handle>`, because a seat without that session never hears the task.
#      --room-check-only runs only this phase against an existing set (--prefix and --room required).
#
# VERIFIED 2026-09-23 on jam 0.4.10 / Windows 11 through the PowerShell twin (see ../DRY-RUN.md): `agent create`
# needs --session <scope>; a subscription seat needs --claude-context-mode local_config (bare pairs only with
# api_key); the handle is owner/<name>; mandates are LIVE-LINKED to the file path (point MANDATE_DIR at the
# committed mandates the judges scan); permission mode auto ran whole units with no prompt except for destructive
# commands; a seat cannot create the room the human must be in; only a seat with a running worker gets a room
# session when added to a room, and a stopped worker cannot be restarted or bound from the CLI.
# Rule baked in: never a Fable/Mythos model in a headless seat (bills usage credits without a prompt).
# Off-quota builder (2026-09-25): BUILDER_SPAWN=<provider wrapper> with BUILDER_MODEL=<the provider's model id> creates
# ONLY the builder with api_key auth, bare context and that spawn command; the other seats stay on the subscription.
# Same refusals and effort default (max) as the PowerShell twin, where the auto-mode probe is recorded.
# Clean seats (2026-09-26): SEAT_CONFIG_DIR=<folder> spawns every subscription seat through a wrapper the script writes
# into that folder (it sets CLAUDE_CONFIG_DIR before exec'ing the unmodified claude binary), so no personal CLAUDE.md,
# rules, hooks, skills, agent types or plugins of the host reach a seat. The folder holds only a sign-in, made once by the
# human with `CLAUDE_CONFIG_DIR=<folder> claude auth login`; the script refuses a folder that is not signed in.
#
# Per-seat launchers (2026-09-26): with SEAT_CONFIG_DIR, each seat gets its own launcher spawn-<seat>.sh that also sets the
# seat's git author and committer ("Release Clerk <release-clerk@factory-seats.invalid>"), so every commit names its seat,
# disables Claude Code background tasks (CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1: a background job's completion does not
# wake a seat in the room, and a reply staged before it was lost in a rehearsal) and sets long Bash timeouts.
# --plain-names names each seat by its role alone ("architect"), so the room's seat names match mandates/<seat>.md.
#
# Usage: ./standup.sh <workspace-dir> [<mandate-dir>] [--dry-run] [--prefix <p>] [--plain-names] [--room <room-id>] [--add-via <scope>] [--room-check-only]
#   env overrides: ARCHITECT_MODEL CRITIC_MODEL DESIGNER_MODEL BUILDER_MODEL VERIFIER_MODEL CLERK_MODEL ARCHITECT_EFFORT CRITIC_EFFORT DESIGNER_EFFORT BUILDER_EFFORT VERIFIER_EFFORT CLERK_EFFORT BUILDER_SPAWN SEAT_CONFIG_DIR PREFIX AUTH PERMISSION_MODE MIN_CLAUDE_VERSION ROOM_WAIT_SECONDS
set -euo pipefail

WORKSPACE="${1:?usage: standup.sh <workspace-dir> [<mandate-dir>] [--dry-run] [--prefix <p>] [--plain-names] [--room <room-id>] [--add-via <scope>] [--room-check-only]}"; shift
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANDATE_DIR="$HERE/../mandates"
DRY_RUN=""; ROOM_ID=""; ADD_VIA=""; ROOM_CHECK_ONLY=""; PLAIN_NAMES=""
PREFIX="${PREFIX:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --room) ROOM_ID="${2:?--room needs a room id}"; shift ;;
    --add-via) ADD_VIA="${2:?--add-via needs a session scope}"; shift ;;
    --prefix) PREFIX="${2:?--prefix needs a value}"; shift ;;
    --room-check-only) ROOM_CHECK_ONLY=1 ;;
    --plain-names) PLAIN_NAMES=1 ;;
    *) MANDATE_DIR="$1" ;;
  esac
  shift
done
if [ -z "$PREFIX" ]; then
  if [ -n "$ROOM_CHECK_ONLY" ] && [ -z "$PLAIN_NAMES" ]; then echo "--room-check-only needs --prefix (the prefix the stand-up printed)" >&2; exit 2; fi
  PREFIX="f$(date +%m%d-%H%M)"
fi
if [ -n "$ROOM_CHECK_ONLY" ] && [ -z "$ROOM_ID" ]; then echo "--room-check-only needs --room" >&2; exit 2; fi
# Jam cuts a handle to 24 characters (VERIFIED 2026-09-23: --name factory-260923-1859-architect became the handle
# lippincdev/factory-260923-1859-arch). A cut handle still works, but the mention in the task and the room reads
# wrong and the prefix stops being recognisable, so refuse before creating anything.
longest="$PREFIX-release-clerk"
if [ "${#longest}" -gt 24 ]; then echo "prefix '$PREFIX' is too long: the handle '$longest' would run past 24 characters and Jam would cut it. Use at most 10 characters (the default is f<mmdd>-<hhmm>)." >&2; exit 2; fi
AUTH="${AUTH:-subscription}"
PERMISSION_MODE="${PERMISSION_MODE:-auto}"
MIN_CLAUDE_VERSION="${MIN_CLAUDE_VERSION:-2.1.280}"
ROOM_WAIT_SECONDS="${ROOM_WAIT_SECONDS:-90}"
ARCHITECT_MODEL="${ARCHITECT_MODEL:-claude-opus-5-5}"
CRITIC_MODEL="${CRITIC_MODEL:-claude-opus-5-5}"
DESIGNER_MODEL="${DESIGNER_MODEL:-claude-opus-5-5}"
BUILDER_MODEL="${BUILDER_MODEL:-claude-opus-5-5}"
VERIFIER_MODEL="${VERIFIER_MODEL:-claude-opus-5-5}"
CLERK_MODEL="${CLERK_MODEL:-claude-opus-5-5}"
ARCHITECT_EFFORT="${ARCHITECT_EFFORT:-xhigh}"
CRITIC_EFFORT="${CRITIC_EFFORT:-xhigh}"
DESIGNER_EFFORT="${DESIGNER_EFFORT:-xhigh}"
VERIFIER_EFFORT="${VERIFIER_EFFORT:-xhigh}"
CLERK_EFFORT="${CLERK_EFFORT:-high}"

for m in "$ARCHITECT_MODEL" "$CRITIC_MODEL" "$DESIGNER_MODEL" "$BUILDER_MODEL" "$VERIFIER_MODEL" "$CLERK_MODEL"; do
  case "$m" in *fable*|*mythos*) echo "Refusing: '$m' is a Fable/Mythos model; headless seats run Opus or Sonnet only." >&2; exit 2;; esac
done
case "$AUTH" in subscription) CONTEXT_MODE=local_config ;; api_key) CONTEXT_MODE=bare ;; *) echo "AUTH must be subscription or api_key" >&2; exit 2 ;; esac
# An off-quota builder: the provider wrapper must exist and must be paired with the provider's own model id (a claude-*
# id behind a provider endpoint is silently mapped; a provider id on the subscription runtime fails in the room).
BUILDER_SPAWN="${BUILDER_SPAWN:-}"
if [ -n "$BUILDER_SPAWN" ]; then
  [ -e "$BUILDER_SPAWN" ] || { echo "BUILDER_SPAWN '$BUILDER_SPAWN' does not exist." >&2; exit 2; }
  case "$BUILDER_MODEL" in claude-*) echo "BUILDER_SPAWN needs the provider's model id in BUILDER_MODEL (e.g. glm-5.3), not '$BUILDER_MODEL': a claude-* id behind a provider endpoint is silently mapped to another model." >&2; exit 2;; esac
  BUILDER_AUTH=api_key; BUILDER_CONTEXT_MODE=bare
else
  case "$BUILDER_MODEL" in claude-*) ;; *) echo "BUILDER_MODEL '$BUILDER_MODEL' is not a Claude model, so it needs BUILDER_SPAWN=<provider wrapper>; the subscription runtime cannot serve it." >&2; exit 2;; esac
  BUILDER_AUTH="$AUTH"; BUILDER_CONTEXT_MODE="$CONTEXT_MODE"
fi
if [ -z "${BUILDER_EFFORT:-}" ]; then if [ -n "$BUILDER_SPAWN" ]; then BUILDER_EFFORT=max; else BUILDER_EFFORT=high; fi; fi
echo "Builder: $BUILDER_MODEL at effort $BUILDER_EFFORT${BUILDER_SPAWN:+ via $BUILDER_SPAWN (api_key, bare; off the Claude subscription)}"
mkdir -p "$WORKSPACE"; WORKSPACE="$(cd "$WORKSPACE" && pwd)"
MANDATE_DIR="$(cd "$MANDATE_DIR" && pwd)"

# Clean seats: a config folder holding only a sign-in, and a wrapper that points the seat's claude at it.
SEAT_CONFIG_DIR="${SEAT_CONFIG_DIR:-}"
SEAT_SPAWN=""
if [ -n "$SEAT_CONFIG_DIR" ]; then
  [ -d "$SEAT_CONFIG_DIR" ] || { echo "SEAT_CONFIG_DIR '$SEAT_CONFIG_DIR' does not exist. Create it and sign in once: CLAUDE_CONFIG_DIR='$SEAT_CONFIG_DIR' claude auth login" >&2; exit 2; }
  SEAT_CONFIG_DIR="$(cd "$SEAT_CONFIG_DIR" && pwd)"
  CLAUDE_BIN="$(command -v claude || true)"
  [ -n "$CLAUDE_BIN" ] || { echo "claude is not on PATH; the seats spawn it." >&2; exit 2; }
  # Read-only, so it runs in a dry run too.
  if ! CLAUDE_CONFIG_DIR="$SEAT_CONFIG_DIR" "$CLAUDE_BIN" auth status 2>&1 | grep -qE '"loggedIn": *true'; then
    echo "the seat config folder $SEAT_CONFIG_DIR is not signed in. The human signs in once: CLAUDE_CONFIG_DIR='$SEAT_CONFIG_DIR' claude auth login" >&2; exit 2
  fi
  SEAT_SPAWN="$SEAT_CONFIG_DIR/spawn-<seat>.sh"
  for role in architect critic designer builder verifier release-clerk; do
    pretty="$(printf '%s' "$role" | tr '-' ' ' | awk '{for (i = 1; i <= NF; i++) $i = toupper(substr($i, 1, 1)) substr($i, 2); print}')"
    mail="$role@factory-seats.invalid"
    if [ -z "$DRY_RUN" ]; then
      printf '#!/bin/sh\n# spawn-%s.sh - written by standup.sh: start the unmodified claude binary for the %s seat with a clean\n# config folder (a sign-in only), so no personal CLAUDE.md, rules, hooks, skills, agents or plugins reach the seat;\n# the seat commits under its own name, never runs a background task, and gets long Bash timeouts.\nGIT_AUTHOR_NAME="%s" GIT_AUTHOR_EMAIL="%s" GIT_COMMITTER_NAME="%s" GIT_COMMITTER_EMAIL="%s" \\\n  CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 BASH_DEFAULT_TIMEOUT_MS=1200000 BASH_MAX_TIMEOUT_MS=3600000 \\\n  CLAUDE_CONFIG_DIR="%s" exec "%s" "$@"\n' "$role" "$role" "$pretty" "$mail" "$pretty" "$mail" "$SEAT_CONFIG_DIR" "$CLAUDE_BIN" > "$SEAT_CONFIG_DIR/spawn-$role.sh"
      chmod +x "$SEAT_CONFIG_DIR/spawn-$role.sh"
    fi
  done
  echo "Clean seats: each spawned through its own $SEAT_SPAWN (CLAUDE_CONFIG_DIR=$SEAT_CONFIG_DIR; git name per seat; background tasks off)"
fi

# The CLI is `band` in newer Band Desktop builds and `jam` in 0.4.x.
if command -v band >/dev/null 2>&1; then CLI=band; elif command -v jam >/dev/null 2>&1; then CLI=jam; else echo "Neither 'band' nor 'jam' is on PATH. Install Band Desktop and enable the Claude Code integration first." >&2; exit 2; fi
echo "CLI: $CLI $("$CLI" --version 2>&1 | head -n1)"
echo "Seat prefix: $PREFIX"

run() {
  echo "$CLI $*"
  if [ -n "$DRY_RUN" ]; then return 0; fi
  "$CLI" "$@"
}
run_soft() {   # same, but a failure is reported, not fatal
  echo "$CLI $*"
  if [ -n "$DRY_RUN" ]; then return 0; fi
  "$CLI" "$@" || echo "  (command failed: $CLI $*)"
}
# `jam list` prints every seat whatever the scope; this seat's line reads "<owner>/<handle> [<session name>] Connected running=true".
# The handle is the name cut to 24 characters, so match on the bracketed session name, never on the handle.
seat_line() {
  "$CLI" list --session "$1" 2>/dev/null | grep -F "[$1]" | head -n1 || true
}
check_claude_version() {
  command -v claude >/dev/null 2>&1 || { echo "claude is not on PATH; the seats spawn it. Install Claude Code and sign in first." >&2; exit 2; }
  local raw have lowest
  raw="$(claude --version 2>&1 | head -n1)"
  have="$(printf '%s\n' "$raw" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1 || true)"
  [ -n "$have" ] || { echo "cannot read the Claude Code version from '$raw'" >&2; exit 2; }
  echo "Claude Code: $have at $(command -v claude) (need at least $MIN_CLAUDE_VERSION)"
  lowest="$(printf '%s\n%s\n' "$MIN_CLAUDE_VERSION" "$have" | sort -t. -k1,1n -k2,2n -k3,3n | head -n1)"
  if [ "$lowest" != "$MIN_CLAUDE_VERSION" ]; then
    echo "Claude Code $have is older than $MIN_CLAUDE_VERSION; run 'claude update' first. An older runtime fails a claude-opus-5-5 seat's first turn with a 400 that shows up only as a room error message." >&2
    exit 2
  fi
}
assert_live() {
  [ -n "$DRY_RUN" ] && return 0
  local i line=""
  for i in 1 2 3 4 5 6; do
    line="$(seat_line "$1")"
    case "$line" in *running=true*) echo "  live: $line"; return 0;; esac
    sleep 2
  done
  echo "seat $1 is not running ('$line'). A seat whose worker is stopped cannot be started or bound from the CLI: create the set again under a new prefix (the default is a fresh timestamp)." >&2
  exit 2
}

SEATS="architect critic designer builder verifier release-clerk"
seat_model()  { case "$1" in architect) echo "$ARCHITECT_MODEL";; critic) echo "$CRITIC_MODEL";; designer) echo "$DESIGNER_MODEL";; builder) echo "$BUILDER_MODEL";; verifier) echo "$VERIFIER_MODEL";; release-clerk) echo "$CLERK_MODEL";; esac; }
seat_effort() { case "$1" in architect) echo "$ARCHITECT_EFFORT";; critic) echo "$CRITIC_EFFORT";; designer) echo "$DESIGNER_EFFORT";; builder) echo "$BUILDER_EFFORT";; verifier) echo "$VERIFIER_EFFORT";; release-clerk) echo "$CLERK_EFFORT";; esac; }
seat_auth()   { case "$1" in builder) echo "$BUILDER_AUTH";; *) echo "$AUTH";; esac; }
seat_mode()   { case "$1" in builder) echo "$BUILDER_CONTEXT_MODE";; *) echo "$CONTEXT_MODE";; esac; }
seat_spawn()  { if [ "$1" = builder ] && [ -n "$BUILDER_SPAWN" ]; then echo "$BUILDER_SPAWN"; elif [ -n "$SEAT_CONFIG_DIR" ]; then echo "$SEAT_CONFIG_DIR/spawn-$1.sh"; fi; }
agent_name()  { if [ -n "$PLAIN_NAMES" ]; then echo "$1"; else echo "$PREFIX-$1"; fi; }
HANDLE_ARCHITECT=""; HANDLE_CRITIC=""; HANDLE_DESIGNER=""; HANDLE_BUILDER=""; HANDLE_VERIFIER=""; HANDLE_CLERK=""
set_handle() { case "$1" in architect) HANDLE_ARCHITECT="$2";; critic) HANDLE_CRITIC="$2";; designer) HANDLE_DESIGNER="$2";; builder) HANDLE_BUILDER="$2";; verifier) HANDLE_VERIFIER="$2";; release-clerk) HANDLE_CLERK="$2";; esac; }
get_handle() { case "$1" in architect) echo "$HANDLE_ARCHITECT";; critic) echo "$HANDLE_CRITIC";; designer) echo "$HANDLE_DESIGNER";; builder) echo "$HANDLE_BUILDER";; verifier) echo "$HANDLE_VERIFIER";; release-clerk) echo "$HANDLE_CLERK";; esac; }
handle_of_line() { printf '%s\n' "$1" | grep -oE '[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+' | head -n1 || true; }

wait_room_sessions() {
  if [ -n "$DRY_RUN" ]; then echo "(dry run) would wait up to $ROOM_WAIT_SECONDS s for a default-$ROOM_ID session on every seat"; return 0; fi
  echo "Waiting up to $ROOM_WAIT_SECONDS s for a default-$ROOM_ID session on every seat..."
  local end missing name line state
  end=$(( $(date +%s) + ROOM_WAIT_SECONDS ))
  while :; do
    missing=""
    for name in $SEATS; do
      line="$("$CLI" sessions --as "$(get_handle "$name")" 2>/dev/null | grep -E "^default-$ROOM_ID( |$)" | head -n1 || true)"
      if [ -n "$line" ]; then
        state="$(printf '%s\n' "$line" | grep -oE 'presence=[^ ]+ binding=[^ ]+' | head -n1 || true)"
        printf '  %-14s room session present: %s\n' "$name" "${state:-(state not shown)}"
      else
        missing="$missing $name"
      fi
    done
    [ -z "$missing" ] && return 0
    [ "$(date +%s)" -ge "$end" ] && break
    sleep 5
  done
  echo "no room session for:$missing. A seat without a default-$ROOM_ID session never hears the task. Add it to the room in Band Desktop (Participants) while its worker is running, or from a live member seat: $CLI chat add --session <live member scope> $ROOM_ID <owner/handle>; then run this script again with --room-check-only." >&2
  exit 2
}

# 0. Preflight, then the CLI version the seats will spawn.
run preflight
check_claude_version

if [ -n "$ROOM_CHECK_ONLY" ]; then
  for name in $SEATS; do
    agent="$(agent_name "$name")"
    existing="$(seat_line "$agent")"
    [ -n "$existing" ] || { echo "seat $agent does not exist; run the stand-up without --room-check-only first." >&2; exit 2; }
    handle="$(handle_of_line "$existing")"; [ -n "$handle" ] || handle="<owner>/$agent"
    set_handle "$name" "$handle"
    assert_live "$agent"
  done
else
  # 1. Workspace files that keep seat work generic.
  TEMPLATE_DIR="$HERE/workspace"; [ -d "$TEMPLATE_DIR" ] || TEMPLATE_DIR="$HERE/../workspace"
  if [ -f "$TEMPLATE_DIR/CLAUDE.md" ]; then cp "$TEMPLATE_DIR/CLAUDE.md" "$WORKSPACE/CLAUDE.md"; echo "wrote $WORKSPACE/CLAUDE.md"; fi
  if [ -f "$TEMPLATE_DIR/settings.local.json" ]; then
    mkdir -p "$WORKSPACE/.claude"; cp "$TEMPLATE_DIR/settings.local.json" "$WORKSPACE/.claude/settings.local.json"
    [ -d "$WORKSPACE/.git" ] && echo ".claude/settings.local.json" >> "$WORKSPACE/.git/info/exclude"
    echo "wrote $WORKSPACE/.claude/settings.local.json"
  fi

  # 2. Create the seats fresh (a seat with a running worker is kept; a stopped one is refused), attach the mandates,
  #    and require a running worker on each.
  for name in $SEATS; do
    mandate="$MANDATE_DIR/$name.md"
    [ -f "$mandate" ] || { echo "missing mandate: $mandate" >&2; exit 2; }
    agent="$(agent_name "$name")"
    existing=""
    if [ -z "$DRY_RUN" ]; then existing="$(seat_line "$agent")"; fi
    if [ -n "$existing" ]; then
      case "$existing" in
        *running=true*) echo "  seat exists with a running worker, keeping it: $existing" ;;
        *) echo "seat $agent exists but its worker is stopped ('$existing'); it cannot be restarted or bound from the CLI. Run again with a new prefix (the default is a fresh timestamp)." >&2; exit 2 ;;
      esac
    else
      spawn_path="$(seat_spawn "$name")"
      run agent create \
        --session "$agent" \
        --name "$agent" \
        --description "Factory seat: $name. Generic mandate; see the room plan for the task." \
        --cwd "$WORKSPACE" \
        --transport claude-code-cli \
        --runtime-auth "$(seat_auth "$name")" \
        --runtime-model "$(seat_model "$name")" \
        --runtime-effort "$(seat_effort "$name")" \
        --claude-context-mode "$(seat_mode "$name")" \
        --claude-permission-mode "$PERMISSION_MODE" \
        ${spawn_path:+--spawn-command "$spawn_path"}
      if [ -z "$DRY_RUN" ]; then existing="$(seat_line "$agent")"; fi
    fi
    handle="$(handle_of_line "$existing")"; [ -n "$handle" ] || handle="<owner>/$agent"
    set_handle "$name" "$handle"
    run agent instructions set --as "$handle" --instructions-file "$mandate"
    run agent instructions show --as "$handle"
    assert_live "$agent"
  done
fi

# 3. The room: the human creates it in Band Desktop and adds the seats while their workers run, or a live member
#    seat adds them. Either way, every seat must show a session for the room.
if [ -n "$ROOM_ID" ]; then
  handles="$(get_handle architect) $(get_handle critic) $(get_handle builder) $(get_handle verifier) $(get_handle release-clerk)"
  if [ -n "$ADD_VIA" ]; then
    # shellcheck disable=SC2086
    run_soft chat add --session "$ADD_VIA" "$ROOM_ID" $handles
  else
    # A fresh seat cannot add itself or its set (VERIFIED 2026-09-23: "no reachable peer" for its own handle, HTTP 404
    # for the others), so without --add-via the human's click in Band Desktop is the only way in.
    echo "No --add-via given: add the seats in Band Desktop (Participants) now if you have not; waiting for their room sessions."
  fi
  wait_room_sessions
fi

echo
echo "Seats:"
for name in $SEATS; do printf '  %-14s %s\n' "$name" "$(get_handle "$name")"; done
if [ -n "$ROOM_ID" ]; then
  echo "Room $ROOM_ID: every seat has a session. Next: start the recording, then post the task as the human:"
  echo "  $CLI room participants $ROOM_ID                      (the architect's participant id)"
  echo "  $CLI room send $ROOM_ID \"<task text>\" --mention <architect participant id>"
else
  echo "Next (the human, in Band Desktop): Rooms -> New room -> add the six seats (Participants) while their workers run, then:"
  echo "  $0 $WORKSPACE $( [ -n "$PLAIN_NAMES" ] && echo --plain-names || echo --prefix $PREFIX) --room <room id> --room-check-only"
  echo "Only after that check passes: start the recording and post the task addressed to @$(get_handle architect)."
fi
echo "Recording: capture the screen REGION the Band Desktop window occupies (window maximized and in front; even dimensions; look at one frame of a 5-s test first) with ffmpeg avfoundation (macOS) or x11grab (Linux), -c:v libx264 -preset veryfast -pix_fmt yuv420p room.mkv; on Windows the twin prints the gdigrab form."
echo "Watch from a terminal: $CLI room messages <room-id> --type text ; permissions: $CLI permissions list --as <owner/handle>"
