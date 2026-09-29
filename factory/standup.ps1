<#
.SYNOPSIS
  Stand up the factory seats: five Band Desktop agents (architect, critic, builder, verifier, release clerk; headless
  Claude Code runtimes owned by Band Desktop, all on claude-opus-5-5 by default since 2026-09-26),
  each with its generic mandate as owner instructions, plus the workspace files that keep seat work generic;
  then check the three things the dry runs of 2026-09-23 showed must be true before a task is pasted.

.DESCRIPTION
  Phases; each stops the script with a plain reason when its check fails:
    0. Preconditions: `jam preflight`, and the Claude Code CLI the seats spawn is at least -MinClaudeVersion
       (2.1.280: an older runtime fails the first turn of a claude-opus-5-5 seat with a 400 that shows up only as
       a room error message; the fix is `claude update`).
    1. Workspace files: a generic CLAUDE.md and a settings.local.json that disables unrelated plugins.
    2. Seats, created FRESH under -Prefix (default: f<mmdd>-<hhmm>; at most 10 characters, because Jam cuts a handle
       to 24 and the longest seat name is release-clerk) with `jam agent create`, mandates attached
       with `jam agent instructions set` (live-linked to the mandate files). A seat that already exists is kept only
       while its worker is running; a stopped worker cannot be started or bound from the CLI, so the script refuses
       and asks for a new prefix. Every seat must then show `Connected running=true` in `jam list`: a seat receives
       room membership and mentions only while its worker runs.
    3. The room (with -RoomId): the human creates it in Band Desktop and adds the seats (a live seat binds on add),
       or a live seat that is already a member adds them (-AddVia <its session scope>); a fresh seat cannot add itself
       or its set (VERIFIED 2026-09-23). However they were added, the script then waits until every seat shows a
       `default-<room id>` session in `jam sessions --as <handle>`, because a seat without that session never hears
       the task. -RoomCheckOnly runs only this phase against an existing set (-Prefix and -RoomId required).

.NOTES
  VERIFIED 2026-09-23 on jam 0.4.10, Windows 11 (see ../DRY-RUN.md):
    - `jam agent create` needs --session <scope> (one scope per seat); a subscription seat needs
      --claude-context-mode local_config (bare pairs only with api_key auth);
    - Jam uses --name verbatim as the handle (owner/name); mandates attach with
      `jam agent instructions set --instructions-file` and are LIVE-LINKED to that path, so point -MandateDir
      at the committed mandates the judges scan, not at a scratch copy;
    - `--claude-permission-mode auto` ran whole units with no permission prompt except for destructive commands;
    - a seat cannot create the room that the human must be a participant of; the human creates it in Band Desktop;
    - only a seat with a running worker gets a room session when it is added to a room (second dry run), and a
      seat whose worker stopped after an earlier unit cannot be restarted, invited or bound from the CLI.
  Rule baked in: never a Fable/Mythos model in a headless seat (bills usage credits without a prompt).

  Clean seats (2026-09-26): with -SeatConfigDir <folder>, every subscription seat is spawned through a wrapper the script
  writes into that folder, which sets CLAUDE_CONFIG_DIR to it before starting the unmodified claude binary. The seats
  then load none of the host owner's personal Claude Code layer (CLAUDE.md, rules, hooks, skills, agent types, plugins);
  the folder holds only a sign-in (`$env:CLAUDE_CONFIG_DIR = '<folder>'; claude auth login`, once, by the human). The
  script refuses a folder that is not signed in. Without -SeatConfigDir the workspace settings file still excludes the
  host's CLAUDE.md and rules files and denies the Agent, Workflow and Skill tools (VERIFIED 2026-09-26 with a control
  run), but the host's hooks and listings still reach the seats.

  Off-quota builder (2026-09-25, Martin's pick for the hackathon week): -BuilderSpawn <provider wrapper> with
  -BuilderModel <the provider's model id> creates ONLY the builder with api_key auth, bare context and that spawn
  command (the seat runs the unmodified Claude Code binary against the provider; nothing touches the Max login).
  The other three seats stay on the subscription. The wrapper for the GLM plan is ~\.claude-legs\seat-glm.cmd.
  VERIFIED 2026-09-25 through that wrapper, headless, bare, glm-5.3: auto permission mode runs a literal-path write
  and its classifier blocks an indirect recursive delete (the classifier's calls go to the provider, not to Claude).
  NOT yet verified: Jam accepting --runtime-effort max for such a seat, and a whole unit built by it (the practice
  unit in FACTORY.md proves both before the recorded run).
  Fallback: -Only builder with a NEW -Prefix and no -BuilderSpawn stands up a subscription builder alone for the
  running room (the human adds it and tells the architect the new handle).

.EXAMPLE
  powershell -File standup.ps1 -Workspace C:\work\factory -MandateDir C:\work\submission\mandates -DryRun
  powershell -File standup.ps1 -Workspace C:\work\factory -MandateDir C:\work\submission\mandates
  powershell -File standup.ps1 -Workspace C:\work\factory -BuilderModel glm-5.3 -BuilderSpawn $HOME\.claude-legs\seat-glm.cmd
  powershell -File standup.ps1 -Workspace C:\work\factory -Prefix f0926-1805 -RoomId <room id from Band Desktop> -RoomCheckOnly
#>
param(
  [Parameter(Mandatory = $true)] [string] $Workspace,
  [string] $MandateDir = "",
  [string] $ArchitectModel = "claude-opus-5-5",
  [string] $CriticModel    = "claude-opus-5-5",
  [string] $DesignerModel  = "claude-opus-5-5",
  [string] $BuilderModel   = "claude-opus-5-5",
  [string] $VerifierModel  = "claude-opus-5-5",
  [string] $ClerkModel     = "claude-opus-5-5",
  [string] $ArchitectEffort = "xhigh",
  [string] $CriticEffort    = "xhigh",
  [string] $DesignerEffort  = "xhigh",
  [string] $BuilderEffort   = "",
  [string] $VerifierEffort  = "xhigh",
  [string] $ClerkEffort     = "high",
  [string] $BuilderSpawn   = "",
  [string] $SeatConfigDir  = "",
  [string[]] $Only         = @(),
  [ValidateSet("subscription", "api_key")] [string] $Auth = "subscription",
  [string] $PermissionMode = "auto",
  [string] $Prefix = "",
  [string] $MinClaudeVersion = "2.1.280",
  [string] $RoomId = "",
  [string] $AddVia = "",
  [int] $RoomWaitSeconds = 90,
  [switch] $RoomCheckOnly,
  [switch] $PlainNames,
  [switch] $DryRun
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $MandateDir) { $MandateDir = Join-Path $here "..\mandates" }
$templateDir = if (Test-Path (Join-Path $here "workspace")) { Join-Path $here "workspace" } else { Join-Path $here "..\workspace" }
if (-not $Prefix) {
  if ($RoomCheckOnly) { throw "-RoomCheckOnly needs -Prefix (the prefix the stand-up printed)." }
  $Prefix = "f" + (Get-Date -Format "MMdd-HHmm")
}
if ($RoomCheckOnly -and -not $RoomId) { throw "-RoomCheckOnly needs -RoomId." }
# Jam cuts a handle to 24 characters (VERIFIED 2026-09-23: --name factory-260923-1859-architect became the handle
# lippincdev/factory-260923-1859-arch). A cut handle still works, but the mention in the task and the room reads
# wrong and the prefix stops being recognisable, so refuse before creating anything.
$longest = "$Prefix-release-clerk"
if ($longest.Length -gt 24) { throw "prefix '$Prefix' is too long: the handle '$longest' would run past 24 characters and Jam would cut it. Use at most 10 characters (the default is f<mmdd>-<hhmm>)." }

foreach ($m in @($ArchitectModel, $CriticModel, $DesignerModel, $BuilderModel, $VerifierModel, $ClerkModel)) {
  if ($m -match "fable|mythos") { throw "Refusing: '$m' is a Fable/Mythos model; headless seats run Opus or Sonnet only." }
}
# An off-quota builder: the provider wrapper must exist and must be paired with the provider's own model id. A claude-*
# id behind a provider endpoint is silently mapped to some other model, and a provider id on the subscription runtime
# fails the seat's first turn with an error that shows up only in the room.
if ($BuilderSpawn) {
  if (-not (Test-Path $BuilderSpawn)) { throw "-BuilderSpawn '$BuilderSpawn' does not exist." }
  $BuilderSpawn = (Resolve-Path $BuilderSpawn).Path
  if ($BuilderModel -match "^claude-") { throw "-BuilderSpawn needs the provider's model id in -BuilderModel (e.g. glm-5.3), not '$BuilderModel': a claude-* id behind a provider endpoint is silently mapped to another model." }
} elseif ($BuilderModel -notmatch "^claude-") {
  throw "-BuilderModel '$BuilderModel' is not a Claude model, so it needs -BuilderSpawn <provider wrapper> (e.g. `$HOME\.claude-legs\seat-glm.cmd); the subscription runtime cannot serve it."
}
# Effort: Z.ai recommends max for coding and the legacy GLM plan counts prompts, not output tokens, so an off-quota
# builder defaults to max; if Jam refuses the value at create time, run again with -BuilderEffort high.
if (-not $BuilderEffort) { $BuilderEffort = if ($BuilderSpawn) { "max" } else { "high" } }
if (-not (Test-Path $Workspace)) { New-Item -ItemType Directory -Path $Workspace | Out-Null }
$Workspace = (Resolve-Path $Workspace).Path
$MandateDir = (Resolve-Path $MandateDir).Path
$contextMode = if ($Auth -eq "subscription") { "local_config" } else { "bare" }

# Clean seats: a config folder holding only a sign-in, and a wrapper that points the seat's claude at it.
$seatSpawn = ""
if ($SeatConfigDir) {
  if (-not (Test-Path $SeatConfigDir)) { throw "-SeatConfigDir '$SeatConfigDir' does not exist. Create it and sign in once: `$env:CLAUDE_CONFIG_DIR = '$SeatConfigDir'; claude auth login" }
  $SeatConfigDir = (Resolve-Path $SeatConfigDir).Path
  $claudeExe = (Get-Command claude -ErrorAction SilentlyContinue).Source
  if (-not $claudeExe) { throw "claude is not on PATH; the seats spawn it." }
  # Read-only, so it runs in a dry run too.
  $prev = $env:CLAUDE_CONFIG_DIR
  $env:CLAUDE_CONFIG_DIR = $SeatConfigDir
  $status = (& $claudeExe auth status 2>&1) -join "`n"
  $env:CLAUDE_CONFIG_DIR = $prev
  if ($status -notmatch '"loggedIn":\s*true') { throw "the seat config folder $SeatConfigDir is not signed in. The human signs in once: `$env:CLAUDE_CONFIG_DIR = '$SeatConfigDir'; claude auth login" }
  $seatSpawn = Join-Path $SeatConfigDir "spawn-claude.cmd"
  $wrapper = @(
    "@echo off",
    "rem spawn-claude.cmd - written by standup.ps1: start the unmodified claude binary for a factory seat with a clean",
    "rem config folder (a sign-in only), so no personal CLAUDE.md, rules, hooks, skills, agents or plugins reach the seat.",
    "setlocal",
    "set ""CLAUDE_CONFIG_DIR=$SeatConfigDir""",
    """$claudeExe"" %*",
    "endlocal"
  )
  if (-not $DryRun) { Set-Content -Path $seatSpawn -Value $wrapper -Encoding ascii }
  # One wrapper per seat as well, identical except that it sets the seat's own git author and committer, so the
  # history shows which seat made each commit (the rule book reads teamwork from the room log and the git history).
  $script:seatWrappers = @{}
  foreach ($role in @("architect", "critic", "designer", "builder", "verifier", "release-clerk")) {
    $pretty = (Get-Culture).TextInfo.ToTitleCase(($role -replace "-", " "))
    $mail = "$role@factory-seats.invalid"
    $w = Join-Path $SeatConfigDir "spawn-$role.cmd"
    # No background tasks: a background job's completion does not wake a seat in the room, so the unit stalls
    # (toy rehearsal 2026-09-26: the release clerk's reverse check was backgrounded and the clerk never reported).
    # Long foreground commands get room instead: 20 min default, 60 min max.
    $lines = @($wrapper[0..3]) + @("set ""GIT_AUTHOR_NAME=$pretty""", "set ""GIT_AUTHOR_EMAIL=$mail""", "set ""GIT_COMMITTER_NAME=$pretty""", "set ""GIT_COMMITTER_EMAIL=$mail""", "set ""CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1""", "set ""BASH_DEFAULT_TIMEOUT_MS=1200000""", "set ""BASH_MAX_TIMEOUT_MS=3600000""") + @($wrapper[4..($wrapper.Count - 1)])
    if (-not $DryRun) { Set-Content -Path $w -Value $lines -Encoding ascii }
    $script:seatWrappers[$role] = $w
  }
  Write-Host "Clean seats: spawned through $seatSpawn (CLAUDE_CONFIG_DIR=$SeatConfigDir)" -ForegroundColor DarkGray
}

# The CLI is `band` in newer Band Desktop builds and `jam` in 0.4.x; use whichever is on PATH.
$cli = if (Get-Command band -ErrorAction SilentlyContinue) { "band" } elseif (Get-Command jam -ErrorAction SilentlyContinue) { "jam" } else { throw "Neither 'band' nor 'jam' is on PATH. Install Band Desktop and enable the Claude Code integration first." }
Write-Host "CLI: $cli $((& $cli --version 2>&1 | Select-Object -First 1))" -ForegroundColor DarkGray
Write-Host "Seat prefix: $Prefix" -ForegroundColor DarkGray

$seats = @(
  @{ name = "architect";     model = $ArchitectModel; effort = $ArchitectEffort; file = "architect.md";     auth = $Auth; mode = $contextMode; spawn = $seatSpawn },
  @{ name = "critic";        model = $CriticModel;    effort = $CriticEffort;    file = "critic.md";        auth = $Auth; mode = $contextMode; spawn = $seatSpawn },
  @{ name = "designer";      model = $DesignerModel;  effort = $DesignerEffort;  file = "designer.md";      auth = $Auth; mode = $contextMode; spawn = $seatSpawn },
  @{ name = "builder";       model = $BuilderModel;   effort = $BuilderEffort;   file = "builder.md";       auth = $Auth; mode = $contextMode; spawn = $seatSpawn },
  @{ name = "verifier";      model = $VerifierModel;  effort = $VerifierEffort;  file = "verifier.md";      auth = $Auth; mode = $contextMode; spawn = $seatSpawn },
  @{ name = "release-clerk"; model = $ClerkModel;     effort = $ClerkEffort;     file = "release-clerk.md"; auth = $Auth; mode = $contextMode; spawn = $seatSpawn }
)
if ($SeatConfigDir) { foreach ($s in $seats) { $s.spawn = $script:seatWrappers[$s.name] } }
if ($BuilderSpawn) { $b = $seats | Where-Object { $_.name -eq "builder" }; $b.auth = "api_key"; $b.mode = "bare"; $b.spawn = $BuilderSpawn }
# -Only <seat names>: stand up replacement seats for a running room (e.g. a subscription builder when the off-quota one
# is dropped). Use a NEW prefix: an existing seat with a running worker under the same name is kept, not replaced.
# `powershell -File` passes "builder,release-clerk" as one string, so split on commas.
$Only = @($Only | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($Only.Count -gt 0) {
  $known = @($seats | ForEach-Object { $_.name })
  foreach ($o in $Only) { if ($known -notcontains $o) { throw "-Only: unknown seat '$o'; seats are $($known -join ', ')." } }
  $seats = @($seats | Where-Object { $Only -contains $_.name })
}
Write-Host ("Builder: {0} at effort {1}{2}" -f $BuilderModel, $BuilderEffort, $(if ($BuilderSpawn) { " via $BuilderSpawn (api_key, bare; off the Claude subscription)" } else { " on the subscription" })) -ForegroundColor DarkGray

function Invoke-Cli {
  param([string[]] $CliArgs, [switch] $AllowFail, [switch] $Quiet)
  if (-not $Quiet) { Write-Host ("$cli " + ($CliArgs -join " ")) -ForegroundColor Cyan }
  if ($DryRun) { return "" }
  $ErrorActionPreference = "Continue"
  $out = & $cli @CliArgs 2>&1
  $code = $LASTEXITCODE
  $ErrorActionPreference = "Stop"
  if (-not $Quiet) { $out | ForEach-Object { Write-Host "  $_" } }
  if ($code -ne 0 -and -not $AllowFail) { throw "$cli exited $code" }
  return ($out -join "`n")
}

# `jam list` prints every seat whatever the scope; this seat's line reads "<owner>/<handle> [<session name>] Connected running=true".
# The handle is the name cut to 24 characters, so match on the bracketed session name, never on the handle.
function Get-SeatLine {
  param([string] $AgentName)
  $out = Invoke-Cli @("list", "--session", $AgentName) -AllowFail -Quiet
  return ($out -split "`n" | Where-Object { $_ -match ("\[" + [regex]::Escape($AgentName) + "\]") } | Select-Object -First 1)
}

function Test-ClaudeVersion {
  $claude = Get-Command claude -ErrorAction SilentlyContinue
  if (-not $claude) { throw "claude is not on PATH; the seats spawn it. Install Claude Code and sign in first." }
  $raw = (& claude --version 2>&1 | Select-Object -First 1)
  if ("$raw" -notmatch "(\d+\.\d+\.\d+)") { throw "cannot read the Claude Code version from '$raw'" }
  $have = [version] $Matches[1]
  $need = [version] $MinClaudeVersion
  Write-Host ("Claude Code: {0} at {1} (need at least {2})" -f $have, $claude.Source, $need) -ForegroundColor DarkGray
  if ($have -lt $need) { throw "Claude Code $have is older than $need; run 'claude update' first. An older runtime fails a claude-opus-5-5 seat's first turn with a 400 that shows up only as a room error message." }
}

function Assert-Live {
  param([string] $AgentName)
  if ($DryRun) { return }
  $line = ""
  for ($i = 0; $i -lt 6; $i++) {
    $line = Get-SeatLine $AgentName
    if ("$line" -match "running=true") { Write-Host "  live: $line" -ForegroundColor Green; return }
    Start-Sleep -Seconds 2
  }
  throw "seat $AgentName is not running ('$line'). A seat whose worker is stopped cannot be started or bound from the CLI: create the set again under a new -Prefix (the default is a fresh timestamp)."
}

function Wait-RoomSessions {
  param([hashtable] $Handles, [string] $Room, [int] $Seconds)
  if ($DryRun) { Write-Host "(dry run) would wait up to $Seconds s for a default-$Room session on every seat"; return }
  Write-Host "Waiting up to $Seconds s for a default-$Room session on every seat..." -ForegroundColor DarkGray
  $deadline = (Get-Date).AddSeconds($Seconds)
  $missing = @()
  do {
    $missing = @()
    foreach ($k in ($Handles.Keys | Sort-Object)) {
      $out = Invoke-Cli @("sessions", "--as", $Handles[$k]) -AllowFail -Quiet
      $line = ($out -split "`n" | Where-Object { $_ -match ("^default-" + [regex]::Escape($Room) + "(\s|$)") } | Select-Object -First 1)
      if ($line) {
        $state = if ("$line" -match "presence=\S+ binding=\S+") { $Matches[0] } else { "(state not shown)" }
        Write-Host ("  {0,-14} room session present: {1}" -f $k, $state) -ForegroundColor Green
      } else { $missing += $k }
    }
    if ($missing.Count -eq 0) { return }
    Start-Sleep -Seconds 5
  } while ((Get-Date) -lt $deadline)
  throw ("no room session for: {0}. A seat without a default-{1} session never hears the task. Add it to the room in Band Desktop (Participants) while its worker is running, or from a live member seat: {2} chat add --session <live member scope> {1} <owner/handle>; then run this script again with -RoomCheckOnly." -f ($missing -join ", "), $Room, $cli)
}

# 0. Preflight: account, daemon, Claude Code integration; then the CLI version the seats will spawn.
Invoke-Cli @("preflight") | Out-Null
Test-ClaudeVersion

$handles = @{}
if ($RoomCheckOnly) {
  foreach ($s in $seats) {
    $agentName = if ($PlainNames) { $s.name } else { "$Prefix-$($s.name)" }
    $line = Get-SeatLine $agentName
    if (-not $line) { throw "seat $agentName does not exist; run the stand-up without -RoomCheckOnly first." }
    $handles[$s.name] = if ("$line" -match "([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)") { $Matches[1] } else { "<owner>/$agentName" }
    Assert-Live $agentName
  }
} else {
  # 1. Workspace files that keep seat work generic: a one-paragraph CLAUDE.md (committed with the work) and a
  #    local settings file that disables unrelated plugins for the seats (never committed).
  foreach ($f in @("CLAUDE.md")) {
    $src = Join-Path $templateDir $f
    if (Test-Path $src) { Copy-Item $src (Join-Path $Workspace $f) -Force; Write-Host "wrote $Workspace\$f" -ForegroundColor DarkGray }
  }
  $settingsSrc = Join-Path $templateDir "settings.local.json"
  if (Test-Path $settingsSrc) {
    $claudeDir = Join-Path $Workspace ".claude"
    if (-not (Test-Path $claudeDir)) { New-Item -ItemType Directory -Path $claudeDir | Out-Null }
    Copy-Item $settingsSrc (Join-Path $claudeDir "settings.local.json") -Force
    $exclude = Join-Path $Workspace ".git\info\exclude"
    if (Test-Path (Join-Path $Workspace ".git")) { Add-Content -Path $exclude -Value ".claude/settings.local.json" }
    Write-Host "wrote $claudeDir\settings.local.json" -ForegroundColor DarkGray
  }

  # 2. Create the seats fresh (a seat with a running worker is kept; a stopped one is refused), attach the mandates,
  #    and require a running worker on each.
  foreach ($s in $seats) {
    $mandate = Join-Path $MandateDir $s.file
    if (-not (Test-Path $mandate)) { throw "missing mandate: $mandate" }
    $agentName = if ($PlainNames) { $s.name } else { "$Prefix-$($s.name)" }
    $line = if ($DryRun) { "" } else { Get-SeatLine $agentName }
    if ($line -and "$line" -match "running=true") {
      Write-Host "  seat exists with a running worker, keeping it: $line" -ForegroundColor Yellow
    } elseif ($line) {
      throw "seat $agentName exists but its worker is stopped ('$line'); it cannot be restarted or bound from the CLI. Run again with a new -Prefix (the default is a fresh timestamp)."
    } else {
      $createArgs = @(
        "agent", "create",
        "--session", $agentName,
        "--name", $agentName,
        "--description", "Factory seat: $($s.name). Generic mandate; see the room plan for the task.",
        "--cwd", $Workspace,
        "--transport", "claude-code-cli",
        "--runtime-auth", $s.auth,
        "--runtime-model", $s.model,
        "--runtime-effort", $s.effort,
        "--claude-context-mode", $s.mode,
        "--claude-permission-mode", $PermissionMode
      )
      if ($s.spawn) { $createArgs += @("--spawn-command", $s.spawn) }
      Invoke-Cli $createArgs | Out-Null
      $line = if ($DryRun) { "<owner>/$agentName" } else { Get-SeatLine $agentName }
    }
    $handle = if ("$line" -match "([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)") { $Matches[1] } else { "<owner>/$agentName" }
    $handles[$s.name] = $handle
    Invoke-Cli @("agent", "instructions", "set", "--as", $handle, "--instructions-file", $mandate) | Out-Null
    Invoke-Cli @("agent", "instructions", "show", "--as", $handle) | Out-Null
    Assert-Live $agentName
  }
}

# 3. The room. The human must be a participant, so the human creates it in Band Desktop and adds the seats while
#    their workers run; or a live member seat adds them. Either way, every seat must show a session for the room.
if ($RoomId) {
  $all = @($seats | ForEach-Object { $handles[$_.name] })
  if ($AddVia) {
    Invoke-Cli (@("chat", "add", "--session", $AddVia, $RoomId) + $all) -AllowFail | Out-Null
  } else {
    # A fresh seat cannot add itself or its set (VERIFIED 2026-09-23: "no reachable peer" for its own handle, HTTP 404
    # for the others), so without -AddVia the human's click in Band Desktop is the only way in.
    Write-Host "No -AddVia given: add the seats in Band Desktop (Participants) now if you have not; waiting for their room sessions." -ForegroundColor DarkGray
  }
  Wait-RoomSessions -Handles $handles -Room $RoomId -Seconds $RoomWaitSeconds
}

Write-Host ""
Write-Host "Seats:" -ForegroundColor Green
$handles.GetEnumerator() | Sort-Object Name | ForEach-Object { Write-Host ("  {0,-14} {1}" -f $_.Key, $_.Value) }
if ($Only.Count -gt 0) {
  Write-Host "Replacement seat(s) ready. Next (the human): add them to the room in Band Desktop (Participants) while their workers run, run this script again with the same -Prefix -Only -RoomId and -RoomCheckOnly, then tell the architect in the room which handle now holds which seat." -ForegroundColor Green
} elseif ($RoomId) {
  Write-Host "Room ${RoomId}: every seat has a session. Next: start the recording, then post the task as the human:" -ForegroundColor Green
  Write-Host "  $cli room participants $RoomId                      (the architect's participant id)"
  Write-Host "  $cli room send $RoomId ""<task text>"" --mention <architect participant id>"
} else {
  Write-Host "Next (the human, in Band Desktop): Rooms -> New room -> add the five seats (Participants) while their workers run, then:"
  Write-Host "  powershell -File $($MyInvocation.MyCommand.Path) -Workspace $Workspace -Prefix $Prefix -RoomId <room id> -RoomCheckOnly"
  Write-Host "Only after that check passes: start the recording and post the task addressed to @$($handles['architect'])."
}
Write-Host "Recording: capture the screen REGION the Band Desktop window occupies, window maximized and in front (capturing it by title records a blank surface); even dimensions; look at one frame of a 5-s test first: ffmpeg -f gdigrab -framerate 10 -offset_x 0 -offset_y 0 -video_size <even WxH> -i desktop -c:v libx264 -preset veryfast -pix_fmt yuv420p room.mkv"
Write-Host "Watch from a terminal: $cli room messages <room-id> --type text ; permissions: $cli permissions list --as <owner/handle>"
