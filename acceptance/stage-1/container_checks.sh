#!/usr/bin/env bash
# S1-I1 container acceptance checks (verifier seat), from the stage-1 specification.
#
# usage: container_checks.sh <stage-dir> <name-prefix> <free-host-port>
#
#   C1 R10       the Dockerfile in <stage-dir> builds
#   C2 R11/R15/R21/R22  with -e PORT=9123, --cpus 2 --memory 2g on an internal network (no
#                outbound access), GET /health on 9123 answers 200 {"status":"ok"} within 60 s
#   C3 R21       without -e PORT the service answers on 8080
#   C4 R10       RUN.md's command, with only the host port changed, builds and starts the
#                service; /health answers 200 on that host port
#
# Needs Docker and the df-harness-runner image (the in-network probe). Everything it starts
# is named <name-prefix>-cc-* and removed by exact name or id. C4 tags the image RUN.md
# names; it is skipped when that tag already exists, so nobody's image is overwritten.
set -u
STAGE=$1; P=$2-cc; HOST_PORT=$3
NET="$P-net"; IMG="$P:img"
passed=0; failed=0
result() {  # result <PASS|FAIL> <check> <detail>
  echo "$1 $2 $3"
  if [ "$1" = PASS ]; then passed=$((passed + 1)); else failed=$((failed + 1)); fi
}
probe() {  # probe <host> <port> <seconds>: exit 0 once /health answers 200 {"status":"ok"}
  docker run --rm --name "$P-probe" --network "$NET" df-harness-runner python -c "
import json, sys, time, urllib.request
deadline = time.time() + $3
while time.time() < deadline:
    try:
        with urllib.request.urlopen('http://$1:$2/health', timeout=2) as resp:
            if resp.status == 200 and json.load(resp).get('status') == 'ok':
                sys.exit(0)
    except Exception:
        pass
    time.sleep(0.5)
sys.exit(1)"
}
start_and_probe() {  # start_and_probe <check> <container> <port> [docker run env args...]
  local check=$1 name=$2 port=$3; shift 3
  local t0; t0=$(date +%s.%N)
  docker run -d --name "$name" --network "$NET" --cpus 2 --memory 2g "$@" "$IMG" >/dev/null
  if probe "$name" "$port" 60; then
    result PASS "$check" "health_after_s=$(awk -v now="$(date +%s.%N)" -v t0="$t0" 'BEGIN { printf "%.1f", now - t0 }')"
  else
    result FAIL "$check" "no 200 {\"status\":\"ok\"} on port $port within 60 s"
  fi
  docker rm -f "$name" >/dev/null
}

# C1
if docker build -q -t "$IMG" "$STAGE" >/dev/null; then
  result PASS C1_image_builds "$IMG"
  docker network create --internal "$NET" >/dev/null
  outbound=$(docker run --rm --name "$P-probe" --network "$NET" df-harness-runner python -c "
import socket
try:
    socket.create_connection(('1.1.1.1', 80), 3); print('reachable')
except OSError as exc:
    print(exc)" 2>&1)
  echo "INFO network_control outbound 1.1.1.1:80 -> $outbound"
  start_and_probe C2_port_env_and_health_within_60s "$P-port" 9123 -e PORT=9123
  start_and_probe C3_default_port_8080 "$P-default" 8080
  docker network rm "$NET" >/dev/null
  docker rmi "$IMG" >/dev/null
else
  result FAIL C1_image_builds "docker build failed"
fi

# C4
command=$(awk '/^```(sh|bash|shell)?$/{inside=!inside; next} inside && /docker (build|run)/' "$STAGE/RUN.md" | head -1)
tag=$(printf '%s' "$command" | sed -nE 's/.*docker build [^&]*-t ([^ ]+).*/\1/p')
if [ -z "$command" ] || [ -z "$tag" ]; then
  result FAIL C4_run_md_command "no 'docker build -t <tag> ... docker run' command in a code block of RUN.md"
elif [ -n "$(docker images -q "$tag")" ]; then
  echo "SKIP C4_run_md_command image tag '$tag' already exists on this machine"
else
  local_command=$(printf '%s' "$command" | sed -E "s/-p ([0-9.]+:)?[0-9]+:8080/-p $HOST_PORT:8080/")
  echo "INFO C4 command: $local_command"
  before=$(docker ps -q --no-trunc | sort)
  (cd "$STAGE" && bash -c "$local_command") >/dev/null 2>&1 &
  cli=$!
  container=""; ok=""
  for _ in $(seq 1 300); do
    if [ -z "$container" ]; then
      for id in $(comm -13 <(printf '%s\n' "$before") <(docker ps -q --no-trunc | sort)); do
        docker port "$id" 8080 2>/dev/null | grep -q ":$HOST_PORT\$" && container=$id
      done
    fi
    curl -s --max-time 2 "http://127.0.0.1:$HOST_PORT/health" | grep -q '"status": *"ok"' && { ok=1; break; }
    kill -0 "$cli" 2>/dev/null || break
    sleep 1
  done
  if [ -n "$ok" ]; then result PASS C4_run_md_command "health 200 on host port $HOST_PORT"
  else result FAIL C4_run_md_command "RUN.md command gave no healthy service on host port $HOST_PORT"; fi
  [ -n "$container" ] && docker stop "$container" >/dev/null
  wait "$cli" 2>/dev/null
  [ -n "$(docker images -q "$tag")" ] && docker rmi "$tag" >/dev/null
fi
echo "container checks: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
