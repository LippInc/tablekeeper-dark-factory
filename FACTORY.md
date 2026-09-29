# The factory

Status: DRAFT 5 (2026-09-26, night). Rewritten for the event's hands-off rule and the sixth seat (the designer). The measured time and spend of the submitted run are added when the run ends. Track detail lives only in the task text dispatched into the room (template at the end), never in a mandate.

## What it is

A six-seat software factory that runs in one Band Desktop room per run. For each stage, one task is dispatched into the room: that message is the only human input. The seats turn it into a working, verified, packaged stage and end it with a final report; nobody outside the band answers a question, approves, accepts or rejects anything. Every seat is a headless Claude Code runtime owned by Band Desktop, started on demand, with a generic mandate as its owner instructions and nothing else: no personal instructions, hooks, skills or plugins of the machine it runs on. Another team can stand it up with the six mandate files in `mandates/`, the stand-up script in `factory/` and the steps below.

| Seat | Owns (the one thing it writes) | Model and effort (this team) |
|---|---|---|
| architect | the plan with its requirements list, the board and its states, scope, every DECIDED point, the design brief for the foundation decision, the done verdict and the stage's final report | `claude-opus-5-5`, xhigh |
| critic | the verdict on every plan and re-plan (CLEAR, BLOCKED, SPLIT) and an independent, blind answer to the foundation design brief | `claude-opus-5-5`, xhigh |
| designer | the design system file and the look verdict on every change to a screen (APPROVED, CHANGES, UNVERIFIED) | `claude-opus-5-5`, xhigh |
| builder | product code, one commit per concern, each handoff with evidence and a known-bad probe | `claude-opus-5-5`, high |
| verifier | the spec-derived acceptance checks and the verdict on every handoff, reproduced in its own clean checkout | `claude-opus-5-5`, xhigh |
| release clerk | the clean-environment recipe, the delivery layout, the two release gates, the reverse check, the evidence record | `claude-opus-5-5`, high |

**Why one model for all six.** Every seat's output is either the judged result or a gate on it. The practice runs showed what a weaker seat costs: a Sonnet-class release clerk reported a false no-network PASS that only an outside known-bad caught, and a Sonnet-class builder fabricated one probe output and retracted it. Efforts differ by the kind of reasoning: the seats that judge (architect, critic, designer, verifier) run at the top of the band. Each seat is created with the exact model id and effort, and both are visible in the spawned process's command line (`--model claude-opus-5-5 --effort xhigh`, VERIFIED 2026-09-26).

**Why a designer seat.** Half of the application score is a UI that is coherent, presentation-ready, responsive and clear in every state the specification names. In our own preparation, a single agent asked for "a good look" produced a clean, restrained and entirely generic screen, which the human rejected on sight. The designer therefore explores at least three genuinely different rendered directions before it commits a design system, holds a rule against the generic default ("distinctive, not default"), and reviews every screen change at the narrowest required width and at desktop width, in every named state, from a clean checkout served with no network. It never writes product code and never changes anything a check names.

The four answers Band's hacker guide asks a crew to state:
- **The crew:** architect, critic, designer, builder, verifier, release clerk. The human dispatches each stage's task and does nothing else in the room.
- **Who mentions whom, and who is deliberately left out:** the task mentions the architect; the architect mentions one seat at a time; the critic, designer, builder, verifier and release clerk mention only the architect. Nobody but the architect mentions the builder, so it never receives two instructions at once; nobody but the architect asks the critic, the verifier or the designer for a verdict, so no verdict is requested by the seat whose work it judges.
- **The typical flow in one line:** task in, requirements list built from the specification, foundation design answered twice (the critic blind) and reconciled, plan cleared by the critic, design system explored and committed by the designer, one item built with evidence, reproduced by the verifier against its own spec-derived checks, look approved by the designer, packaged, gated and reverse-checked by the clerk, final report.
- **What breaks without the room:** the board is the state of record for every seat's on-wake rule, the mentions are the only routing, and three verdicts stop work in the room itself: the critic's BLOCKED stops a plan, the verifier's REFUTED and the designer's CHANGES stop an item (the guide's "blockable verdicts"); the builder's next step depends on what they found (its "dependent handoffs").

## The loop

1. **Task in.** The stage's task is dispatched into the room addressed to the architect: the stage's specification pasted verbatim, the absolute paths (result repository, stage folder, acceptance-check folder, the organizers' package), the harness commands, the runtime limits, the later stages' specifications for reference, and for a stage with screens the design direction. It is the only human input for the stage.
2. **Requirements list.** Before planning, the architect turns the specification text into a numbered requirements list: every rule, state, response, error, boundary, limit and screen, quoted, one line each, with the item that covers it. Why: only part of each stage's checks ship with the task (for our track 83, 41, 11 and 21 % of stages 1 to 4), every held-back check is written from the specification, and code written to the shipped checks is both incomplete and disqualifying. The specification is the requirement; the provided checks are a sample of it.
3. **Foundation decision (once per task).** Before the first plan, the architect sends the critic a design brief: how data is stored, how simultaneous or repeated requests are kept from interfering, how later stages extend the design, with the complete task text and no recommendation. The critic answers before it opens the plan. Where the two answers differ on something the requirements depend on, the verdict is SPLIT; the architect answers once; a second SPLIT is settled by rule, never by preference or by asking anyone: the reading that keeps more lines of the requirements list satisfiable wins, and on a tie the critic's. The outcome is recorded in the plan as DECIDED, "two-seat" or "two-seat, split settled by rule".
4. **Plan and review.** The architect publishes the room plan (numbered items grouped into units, each with one acceptance line: a command from a clean checkout and its expected output, and the requirement lines it covers) and the board. No item of a plan or re-plan is assigned before the critic's CLEAR. The critic blocks a plan that leaves a requirement line or a provided check without an item, an acceptance line that is prose, work built to a later stage's behaviour, or a claimed property under simultaneous or repeated execution without an item that proves it and a known-bad that would show it failing. A second BLOCKED on the same finding is settled like a second SPLIT.
5. **Design (stages with screens).** Before the first screen item, the architect sends the designer the task's screens, states, layout and visual direction in full. The designer drafts at least three different directions (concept, palette with the meaning of every colour, type pairing, one signature element), renders each at the narrowest required width and at desktop width, judges them side by side against the specification's direction and its own rules, and commits one design system file: tokens, type scale, spacing, focus style, breakpoints, component rules and a layout note per screen and state, plus a paragraph naming the directions that lost and why. Screen items are assigned only after that commit and name it. When the task carries an operator's design direction, the designer explores within it; the specification wins on any difference.
6. **Build.** The architect assigns one item with the complete task text. The builder runs the existing checks on the clean state first, implements the smallest change that satisfies the item's requirement lines, commits only the paths it owns under its own seat name, and hands back an evidence block: files, full commit id, exact commands and output, what is not covered, and one known-bad probe showing the new behaviour's check can fail for the reason under test.
7. **Verify.** The verifier obtains the commit in its own clean directory and writes its own acceptance checks from the specification (not from the builder's code) at the acceptance path, each calibrated against a known-bad before it is trusted; commits only that path; reruns the provided checks and the organizers' harness in the judges' isolated mode; reads the diff and the test bodies; for a property under simultaneous or repeated execution, removes the protection in a throwaway checkout and runs the operation simultaneously and repeatedly (the check must turn red); and returns VERIFIED, REFUTED or UNVERIFIED with commands and output.
8. **Look review (items that change a screen).** After VERIFIED, the designer serves the commit from a clean checkout with outbound network disabled, captures every changed screen at both widths in every named state (including the state after a failed or uncertain action) with a headless browser, and returns APPROVED, CHANGES (each change with the screen, width, state, broken rule or token and the screenshot path) or UNVERIFIED. Only VERIFIED plus, for a screen item, APPROVED moves a board task to verified. A CHANGES verdict counts as a refutation. An item refuted twice is not patched a third time: it is re-planned with a genuinely different approach and the re-plan goes back to the critic.
9. **Repeat.** When a unit has checks that involve simultaneous or repeated execution, the verifier repeats them from a fresh clean checkout of the commit to package, because a race can pass once and fail on a later run.
10. **Package.** The release clerk builds from a clean checkout of the named commit, assembles the stage folder (`Dockerfile`, `RUN.md`, source, no nested `.git`), exercises gate 1 (build, then start with outbound network disabled within the runtime limits and complete a first unit of work) and gate 2 (no credentials, private data or unrelated files), runs the organizers' structure check, and runs the reverse check: the next stage's provided checks must not all pass on this stage's folder (a folder that passes the next stage's whole suite earns nothing for its own stage). Each gate is PASS, FAIL or UNRUNNABLE with the reason; every PASS rests on a negative control that fails for the reason the gate tests.
11. **Final report.** On gates that are PASS or UNRUNNABLE, the architect moves the stage's tasks to done and posts the final report: the items with verdicts and commits, both gates (naming any UNRUNNABLE gate and its reason), the reverse check, the requirements coverage (lines covered, lines not covered and why), the measured wall-clock time, and what the stage does not cover. The final report ends the stage; no seat asks anyone to accept it. The next stage's task arrives after it and works on its own copy of the delivered folder.

Three properties make the loop transferable: a report is never evidence (every claim carries a command and its output another seat can reproduce); every check is calibrated by a known-bad before it is trusted, including the plan (the critic), the acceptance checks (the verifier's calibration) and the no-network gate (a negative control); and each artefact has exactly one writer, so seats never overwrite each other. The board and the git log are the state of record: every mandate has an on-wake rule that reconciles the seat's memory to them.

## How a run stays hands-off

The event's rule is that the dispatched task is the only human input: no approvals, hints, reruns or "looks good, continue". Everything a human used to settle is settled inside the band, and everything that used to stall a run is closed by a rule or a mechanism:

- **Open questions:** the architect answers every question a seat raises; where the task does not settle it, it decides, writes DECIDED with the reason and what would change it into the plan, and moves on. A self-contradicting task: the reading that keeps more requirements satisfiable.
- **Disagreement between seats:** a second SPLIT or a second BLOCKED on the same finding is settled by the rule in step 3, recorded in the plan.
- **What the band cannot fix:** an environment nobody in the band can repair, or a requirement no approach satisfies after a re-plan, is recorded with its evidence in the final report. No seat waits for someone outside the band.
- **Silent seats:** Band wakes a seat only when it is mentioned, so a seat that stops talking wakes nobody. Every seat posts progress messages during long work, and the architect, on every wake, re-sends once any handoff with no reply and no progress for 30 minutes, then reassigns or records the stalled seat.
- **Lost replies:** after posting a verdict, report or handoff, a seat confirms it appears in the room's message list and posts it again if not (see "What we tried that failed", item 5).
- **Background commands:** no seat runs a command in the background. This is enforced, not only asked: the seat launcher sets `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` and long Bash timeouts (20 minutes default, 60 maximum), and a known-bad showed the Bash tool refusing a background run with the variable set and accepting it without (VERIFIED 2026-09-26).
- **A shared machine:** no seat stops, restarts, removes or changes a container, process, service or port binding it did not start in this run; it works around what it finds.
- **Permission prompts:** seats run in Claude Code's `auto` permission mode, which asks only before risky commands; the organizers confirmed that approving a permission prompt is not human input. Seats are told never to run a command that needs a permission decision from outside the band (use a new scratch folder instead, or record the blocker).

## Routing, attention and who the human is

- Band rooms route by mention: only a mentioned agent sees and processes a message. Every seat therefore ends every piece of work with a message that mentions the architect, and every handoff carries the complete task text pasted in full, because a seat that is pointed at "the room" or an earlier message cannot see it.
- One room per run. A development run may be steered; the submitted run is a fresh room and a fresh result repository.
- The human's role in the submitted run: create the room, add the six seats, dispatch each stage's task after the previous stage's final report. On this team a supervising Claude Code session on the human's machine carried out these steps on his instruction while he was away: it created the room in Band Desktop, posted each stage's prepared task under his name word for word, and watched for permission prompts. It sent nothing else into the room. The stage tasks were prepared before the run; the only one with a human choice in it is stage 2's design direction, which the human chose from four rendered directions before the run started.

## Stand-up (what another team does)

Prerequisites: Band Desktop (download list at docs.band.ai/jam; it installs the `jam` CLI), a Band account, Claude Code 2.1.280 or newer on the same machine, Docker, and the organizers' package with its harness. Start Band Desktop normally; its daemon must show as running in `jam preflight`.

1. **A clean configuration folder for the seats.** Create an empty folder and sign Claude Code in once inside it: `CLAUDE_CONFIG_DIR=<folder> claude auth login` (PowerShell: `$env:CLAUDE_CONFIG_DIR = '<folder>'; claude auth login`). The seats are spawned through wrappers that point `CLAUDE_CONFIG_DIR` at this folder, so the machine's personal CLAUDE.md, rules, hooks, skills, agent types and plugins never reach them (VERIFIED 2026-09-26 on the seats' own transcripts). Band's room tools are injected by Band Desktop at spawn.
2. **Seats.** Run `factory/standup-test.ps1` (the script's own known-bads; every check must PASS), then `factory/standup.ps1 -Workspace <folder> -MandateDir <repo>\mandates -SeatConfigDir <folder> -PlainNames`, first with `-DryRun`. The script checks `jam preflight` and the Claude Code version, refuses a seat folder that is not signed in, writes one launcher per seat (it sets that seat's git author and committer name, so every commit shows which seat made it, plus the background and timeout variables above), writes a generic workspace `CLAUDE.md` and a `.claude/settings.local.json` as a second layer, creates the six seats with `jam agent create` (transport `claude-code-cli`, exact model and effort, permission mode `auto`), attaches each mandate with `jam agent instructions set` (live-linked, so point it at the committed mandates), and requires every seat to show `Connected running=true`. `-PlainNames` names each seat after its role, so the room shows "architect" and the mandate file `mandates/architect.md` matches it. On macOS or Linux the same steps are `SEAT_CONFIG_DIR=<folder> factory/standup.sh <workspace> <repo>/mandates --plain-names` (first with `--dry-run`); this team ran the PowerShell script, and the bash twin was checked with a dry run and a launcher test, not a whole run. A Band account holds at most 20 agents (VERIFIED 2026-09-26); remove seat sets you no longer use with `jam rm --as <owner/handle>`.
3. **Room.** In Band Desktop create the room and add the six seats while their workers run. Then run the script again with `-RoomId <room id> -RoomCheckOnly`: it waits until every seat shows a `default-<room id>` session, because a seat without that session never hears the task.
4. **Task.** Post each stage's task addressed to the architect, pasted in Band Desktop or from a bash shell as `jam room send <room id> "$(cat task.txt)" --mention <the architect's participant id from jam room participants>` (a 23,000-character task posts and is stored whole, VERIFIED 2026-09-26).
5. **During the run.** Nothing. Dispatch the next stage after each final report. To watch without touching the room: `factory/room-watch.py <room id>` prints new messages, and `factory/perm-watch.sh` prints any pending permission prompt (a seat blocked on a prompt posts nothing, so the room alone does not show it).
6. **After the run.** In the Band console, "Download full session" and save it unchanged as `room.json` at the repository root; record a slow scroll through the room.

## Evidence conventions (used by every seat)

- Evidence block: item, unit, files changed, full commit id, exact commands from the repository root, output trimmed to the deciding lines, a "not covered" list, one known-bad probe that fails for the reason under test.
- Claim flags: VERIFIED (reproduced by the reader of the claim), VERIFIED-NEGATIVE (searched and found none, with the searching command), DERIVED (follows from a verified statement), ASSUMED (a decision under uncertainty, with what would change it). An ASSUMED statement never decides that a stage is complete.
- Verdicts: item VERIFIED / REFUTED / UNVERIFIED (cause: evidence or environment); look APPROVED / CHANGES / UNVERIFIED; plan CLEAR / BLOCKED / SPLIT; gates PASS / FAIL / UNRUNNABLE.
- Board states: todo, in progress, handed back (marked blocked when it waits for an environment repair), verified, done. The architect is the only mover.
- The evidence record is one committed file in the repository, append-only within a stage; the verifier's checks live in `acceptance/stage-N/`, the design system in `design/`.

## What we tried that failed, and what it changed

1. **The host machine's own Claude Code layer reached every seat** in the first three practice runs (the personal CLAUDE.md, rules, hooks and skill listings, VERIFIED from the seat transcripts). Fix: the clean configuration folder and per-seat launchers.
2. **Weaker models in gate seats.** A Sonnet-class clerk reported a false no-network PASS; a Sonnet-class builder fabricated a probe output. Fix: every seat on Opus 5.5.
3. **A provided check that could not fail.** In a practice run the provided concurrency check stayed green on a known-bad (a key recorded after a one-tick asynchronous yield); the verifier wrote and calibrated its own probe that turned red on it. That became the rule: the verifier writes spec-derived checks at the acceptance path and calibrates each one.
4. **A human accept step.** Draft 4 of this factory ended every unit with the human accepting or rejecting it, and sent a second split to the human. The event's rule book makes the submitted run hands-off, so the final report now ends a stage and splits are settled by rule.
5. **A report that never arrived (rehearsal, 2026-09-26).** The release clerk wrote its packaging report, but its long reverse-check command had been moved to a background task; the reply tool only stages a message until the turn ends, the turn ended on the background task's error, and the staged report was never posted. The clerk believed it had reported and nobody mentioned anybody for 35 minutes. In a hands-off run that ends the run. Fix: background tasks disabled in every launcher (known-bad VERIFIED), the no-background rule and the post-then-confirm delivery check in every mandate.
6. **A shared machine.** During the rehearsal a builder found the host port it wanted held by another project's container, which was redeployed by its own tooling minutes later. Fix: the never-touch rule in every mandate and a note in each task; the clerk ran its gate in a disposable Docker engine with its own ports instead.
7. **A generic first look.** A single-agent design draft (off-white surfaces, one muted accent, a stock sans) was rejected by the human as generic. Fix: the designer seat explores at least three rendered directions before committing, and its mandate names the generic default so it avoids it unless a task asks for it.
8. **Vendoring every dependency.** Our first build constraint required building with no network; the rule book allows the build to fetch dependencies and only the running service is offline. Dropped.
9. **Removing seats.** `jam rm` stopped each practice seat's worker but reported it "could not stop 1 of 1 runtime sessions"; the seats stay registered and count toward the 20-agent limit.

## Runtime and quota

Generic: seats run on whatever Claude Code sign-in the clean folder holds, or on any other runtime Band supports. Seats run only while a message is being handled, so spend tracks the work, not the clock. Never a Fable-class model in a seat: a headless request would bill usage credits with no prompt, and the stand-up script refuses it.

This team: all six seats on one Claude Max subscription, shared with a second event running the same week. If the subscription window runs short, the architect pauses assignment and nothing is lost, because state lives on the board and in git.

## Measured time and cost

- **Practice runs, 2026-09-23** (toy units, four seats, the host layer still loaded): 3 h 14 min / 100 room messages, 44 min / 45, 19 min / 35; each with at least one real refutation; about $45, $6 and $5 of subscription-meter usage.
- **Practice run, 2026-09-26 morning** (five clean seats, human accept still in the loop): 65 minutes from task to the second acceptance, of which about 23 waited for the human; the critic blocked two plan versions before CLEAR; the verifier caught the uncatchable-check case in item 3 above; zero permission prompts.
- **Hands-off rehearsal, 2026-09-26 evening** (six clean seats, toy task, not judged): stage 1 took 2 h 02 min from task to final report, including the 35-minute stall of item 5 and two operator nudges (allowed in a development run); the verifier's spec-derived checks for the single stage-1 item numbered 31, each calibrated. Stage 2 (the first screen, the designer's first design system and look review): added when it completes.
- **Submitted run:** added when the run ends: time per stage, room messages, refutations, and subscription usage.

## Risks carried into the run

1. **A silent stall.** A seat whose runtime dies wakes nobody; the architect's 30-minute re-send covers a seat that is alive but quiet, not a dead runtime. A crashed seat means the run is repeated from scratch in a fresh room (the organizers' answer).
2. **Verification time.** Calibrating every spec-derived check is slow (about an hour for a small toy item); a real stage with many requirement lines may take several hours.
3. **Docker on the host.** Gate 1 needs Docker; if it cannot run, the clerk reports gate 1 UNRUNNABLE, the honest state.
4. **The 20-agent account limit.** A fresh seat set needs an old one removed first.

## Task-message template (the only place track detail lives)

```
Task: stage <N> of <task name>.

HOW THIS RUN WORKS
- This message is the only human input for this stage. Nobody outside the band will answer questions, approve, accept or reject anything until your final report. Resolve every open point inside the band (DECIDED in the plan) and end the stage with the final report.
- Later stages arrive as separate tasks after this stage's final report. Do not start them now, and never build a later stage's behaviour into this stage's folder.

PATHS (absolute)
- Result repository (git, branch main): <path>. README.md, FACTORY.md and mandates/ belong to the operator: do not edit them.
- This stage's folder: <path>\stage-<N>\ (for N > 1: a copy of stage-<N-1>, carried forward and extended). No nested .git.
- Acceptance checks the verifier writes from the specification: <path>\acceptance\stage-<N>\
- Organizers' package (read-only): <path>; this stage's specification, later stages' specifications (reference only), provided checks for stages 1..N, the next stage's checks (reverse check only).
- Scratch and check output: <path>

HOW TO RUN THE ORGANIZERS' HARNESS: <iterate command>; <final command in isolated mode>; what success reads.

THIS MACHINE IS SHARED: <what else runs here; never touch it; use a free port>.
RUNTIME LIMITS: <CPUs, memory, time to healthy, per-request timeout, network>.
BUILD TO THE SPECIFICATION, NOT TO THE CHECKS: <the shipped share of the checks; the held-back checks are written from the specification>.
KEEP THE CODE MAINTAINABLE: <how code quality is judged across stages>.
DESIGN DIRECTION (stages with screens): <the operator's direction and reference pictures, if any>. It adds to the specification's own design requirements and never replaces them: where the two differ, the specification wins. Everything the checks name outranks the look; the look is still part of done.
DONE MEANS: <the stage claims stage N in isolated mode and fails the next suite; both gates and the reverse check reported; the critic cleared the plan; every requirement line covered or explained; the final report posted>.

SPECIFICATION (<path>, verbatim):
<the stage's specification, pasted in full>
```
