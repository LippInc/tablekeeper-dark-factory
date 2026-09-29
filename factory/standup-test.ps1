<#
.SYNOPSIS
  Known-bad checks for standup.ps1: the script must refuse the things it exists to refuse. Run this before the
  stand-up on the event day; a check that cannot fail proves nothing (../DRY-RUN.md, rehearsal of 2026-09-23).

.DESCRIPTION
  Every check feeds standup.ps1 an input it must reject and requires the named refusal, then one dry run must pass.
  Nothing here creates a seat: refusals happen before creation, and the pass case is a -DryRun.
    1. an impossible minimum Claude Code version -> "older than"
    2. a prefix whose longest handle would run past 24 characters -> "too long"
    3. with -StoppedPrefix <p>: a seat set whose workers are stopped -> "worker is stopped" (needs such a set; skip otherwise)
    4. with -LivePrefix <p>: a room id that no seat has a session for -> "no room session" (needs a live set; skip otherwise)
    5. a plain -DryRun -> exit 0 and the "Seats:" summary
    Off-quota builder (2026-09-25):
    6. a non-Claude builder model without -BuilderSpawn -> "needs -BuilderSpawn"
    7. -BuilderSpawn with a claude-* builder model -> "silently mapped"
    8. -BuilderSpawn pointing at a file that does not exist -> "does not exist"
    9. a -DryRun with -BuilderModel glm-5.3 -BuilderSpawn <wrapper> -> exit 0, the builder created with api_key auth,
       the provider model, effort max and the spawn command, and the architect still on the subscription
    10. -Only with an unknown seat -> "unknown seat"; -Only builder -> the builder alone, no architect created

.EXAMPLE
  powershell -File standup-test.ps1 -Workspace C:\work\factory
  powershell -File standup-test.ps1 -Workspace C:\work\factory -StoppedPrefix factory -LivePrefix f0923-1902
#>
param(
  [Parameter(Mandatory = $true)] [string] $Workspace,
  [string] $MandateDir = "",
  [string] $StoppedPrefix = "",
  [string] $LivePrefix = "",
  [string] $SpawnWrapper = "$HOME\.claude-legs\seat-glm.cmd",
  [string] $SeatConfigDir = ""
)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $here "standup.ps1"
$mandateArgs = @(); if ($MandateDir) { $mandateArgs = @("-MandateDir", $MandateDir) }
$fails = 0

function Check {
  param([string] $Name, [string[]] $ScriptArgs, [string] $MustContain, [bool] $MustSucceed, [string] $MustNotContain = "")
  $out = (& powershell -NoProfile -File $script -Workspace $Workspace @mandateArgs @ScriptArgs 2>&1 | Out-String)
  $code = $LASTEXITCODE
  $ok = if ($MustSucceed) { ($code -eq 0) -and ($out -match [regex]::Escape($MustContain)) } else { ($code -ne 0) -and ($out -match [regex]::Escape($MustContain)) }
  if ($MustNotContain -and ($out -match [regex]::Escape($MustNotContain))) { $ok = $false }
  $verdict = if ($ok) { "PASS" } else { "FAIL" }
  Write-Host ("{0}  {1}  (exit {2}; wanted '{3}' {4})" -f $verdict, $Name, $code, $MustContain, $(if ($MustSucceed) { "with exit 0" } else { "with a non-zero exit" }))
  if (-not $ok) { $script:fails++; Write-Host ($out.Substring(0, [Math]::Min(1500, $out.Length))) -ForegroundColor DarkGray }
}

Check "known-bad: impossible minimum version is refused" @("-DryRun", "-MinClaudeVersion", "9.9.9") "older than" $false
Check "known-bad: too-long prefix is refused" @("-DryRun", "-Prefix", "factory-260923-1859") "too long" $false
if ($StoppedPrefix) { Check "known-bad: a stopped seat set is refused" @("-Prefix", $StoppedPrefix) "worker is stopped" $false } else { Write-Host "SKIP  known-bad: stopped seat set (pass -StoppedPrefix <prefix of a set whose workers are stopped>)" }
if ($LivePrefix) { Check "known-bad: a room no seat has a session for fails the room check" @("-Prefix", $LivePrefix, "-RoomId", "00000000-0000-0000-0000-000000000000", "-RoomCheckOnly", "-RoomWaitSeconds", "6") "no room session" $false } else { Write-Host "SKIP  known-bad: room check (pass -LivePrefix <prefix of a live set>)" }
Check "pass case: dry run" @("-DryRun") "Seats:" $true

Check "known-bad: a non-Claude builder without a spawn wrapper is refused" @("-DryRun", "-BuilderModel", "glm-5.3") "needs -BuilderSpawn" $false
if (Test-Path $SpawnWrapper) {
  Check "known-bad: a claude-* builder behind a spawn wrapper is refused" @("-DryRun", "-BuilderModel", "claude-sonnet-5", "-BuilderSpawn", $SpawnWrapper) "silently mapped" $false
  Check "pass case: GLM builder dry run creates the builder off the subscription" @("-DryRun", "-BuilderModel", "glm-5.3", "-BuilderSpawn", $SpawnWrapper) "--runtime-auth api_key --runtime-model glm-5.3 --runtime-effort max --claude-context-mode bare --claude-permission-mode auto --spawn-command $SpawnWrapper" $true
  Check "pass case: GLM builder dry run keeps the judgment seats on the subscription at xhigh" @("-DryRun", "-BuilderModel", "glm-5.3", "-BuilderSpawn", $SpawnWrapper) "--runtime-auth subscription --runtime-model claude-opus-5-5 --runtime-effort xhigh --claude-context-mode local_config" $true
} else { Write-Host "SKIP  GLM builder checks 7 and 9 (no spawn wrapper at $SpawnWrapper; pass -SpawnWrapper <path>)" }
Check "known-bad: a missing spawn wrapper is refused" @("-DryRun", "-BuilderModel", "glm-5.3", "-BuilderSpawn", "C:\no\such\wrapper.cmd") "does not exist" $false
Check "known-bad: -Only with an unknown seat is refused" @("-DryRun", "-Only", "nosuchseat") "unknown seat" $false
Check "pass case: -Only builder stands up the builder alone (the subscription fallback)" @("-DryRun", "-Prefix", "fb0928", "-Only", "builder") "--session fb0928-builder" $true "--session fb0928-architect"

# Five-seat roster, all Opus 5.5 (2026-09-26, the roster evaluation in ../roster-eval-2026-09-26/).
Check "pass case: the default dry run creates the critic seat" @("-DryRun", "-Prefix", "tp0926") "--session tp0926-critic" $true
Check "pass case: the default dry run creates the designer seat at xhigh" @("-DryRun", "-Prefix", "tp0926") "--session tp0926-designer --name tp0926-designer" $true
Check "pass case: -PlainNames names each seat by its role alone" @("-DryRun", "-Prefix", "tp0926", "-PlainNames") "--session release-clerk --name release-clerk" $true
Check "pass case: the default dry run puts every seat on claude-opus-5-5 (no Sonnet seat)" @("-DryRun", "-Prefix", "tp0926") "--runtime-model claude-opus-5-5" $true "claude-sonnet-5"
Check "pass case: the default builder runs at effort high" @("-DryRun", "-Prefix", "tp0926", "-Only", "builder") "--runtime-model claude-opus-5-5 --runtime-effort high" $true
# Clean seats: a missing or signed-out config folder must be refused before anything is created.
Check "known-bad: a missing seat config folder is refused" @("-DryRun", "-SeatConfigDir", "C:\no\such\seat-config") "does not exist" $false
$emptyCfg = Join-Path $env:TEMP "standup-test-empty-seat-config"
if (-not (Test-Path $emptyCfg)) { New-Item -ItemType Directory -Path $emptyCfg | Out-Null }
Check "known-bad: a signed-out seat config folder is refused" @("-DryRun", "-SeatConfigDir", $emptyCfg) "not signed in" $false
if ($SeatConfigDir) {
  Check "pass case: clean seats are spawned through their own config-folder wrapper (architect)" @("-DryRun", "-Prefix", "tp0926", "-SeatConfigDir", $SeatConfigDir) ("--spawn-command " + (Join-Path (Resolve-Path $SeatConfigDir).Path "spawn-architect.cmd")) $true
  Check "pass case: the release clerk gets its own wrapper (its own git name)" @("-DryRun", "-Prefix", "tp0926", "-SeatConfigDir", $SeatConfigDir) ("--spawn-command " + (Join-Path (Resolve-Path $SeatConfigDir).Path "spawn-release-clerk.cmd")) $true
} else { Write-Host "SKIP  clean-seat pass case (pass -SeatConfigDir <a signed-in seat config folder>)" }

Write-Host ""
if ($fails -eq 0) { Write-Host "standup-test: all checks PASS" -ForegroundColor Green; exit 0 } else { Write-Host "standup-test: $fails check(s) FAIL" -ForegroundColor Red; exit 1 }
