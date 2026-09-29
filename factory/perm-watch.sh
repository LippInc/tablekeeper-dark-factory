#!/usr/bin/env bash
# perm-watch.sh - print one line per NEW pending runtime permission request of any factory seat.
# Usage (Monitor): bash perm-watch.sh <band owner, the part before / in a seat handle> [poll seconds, default 60]
# A seat blocked on a prompt posts nothing, so the room watcher never sees it; this does.
# Approving a prompt is not human input (organizers, Q&A 2026-09-26); the operator approves routine requests.
owner="${1:?usage: perm-watch.sh <band owner> [poll seconds]}"
poll="${2:-60}"
seats="architect critic designer builder verifier release-clerk"
declare -A seen
while true; do
  for s in $seats; do
    out="$(jam permissions list --as "$owner/$s" 2>&1)" || true
    case "$out" in
      *"no runtime permissions"*|"") continue ;;
    esac
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      key="$s|$line"
      if [ -z "${seen[$key]}" ]; then
        seen[$key]=1
        echo "[$(date -u +%H:%M)Z] PERMISSION $s: ${line:0:220}"
      fi
    done <<< "$out"
  done
  sleep "$poll"
done
