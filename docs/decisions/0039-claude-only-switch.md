# 0039 — The owner's temporary Claude-only switch

- Status: accepted (owner, 2026-09-28: "bypass the usage rule and use Opus 5.5 high instead
  of ChatGPT Luna 6 Max so that maximum time can be saved")
- Amends: ADR 0035 and ADR 0037 (the final model flow), for as long as the switch is on

## Context

The ChatGPT 5-hour window ran out at about 03:00 UTC, which paused the library run until
about 07:00 UTC. The owner chose to spend their Claude subscription instead of waiting.

## Decision

- **What the switch does.** A Redis key, `radbrain:pipeline:claude_only`, is set with an
  expiry through `pipeline_cli claude-only --hours N`; `--hours 0` turns it off. While it is
  on:
  - every bulk agent (any agent with an approval-gated target) calls only its Claude Opus 5.5
    high target, and ChatGPT is not called at all;
  - interactive agents are unchanged.
- **The ChatGPT pause.** Turning the switch on lifts the ChatGPT quota pause.
- **When Claude's limit runs out.** A spent Claude window pauses the whole run through the
  usual quota pause and owner alert. Pages are not parked for approval.
- **Quality rules stay the same.**
  - Every quality gate still runs.
  - An Opus answer below the bar is kept and goes on the red review list (ADR 0038, rule 11).
- **When it ends.** The switch expires by itself. The final flow (Luna max, then Sol high,
  then Opus after asking) then resumes with no redeploy.

## Consequences

- The run continues while ChatGPT is spent, at the cost of the owner's Claude quota.
- The owner's own Claude Code sessions share that quota.
- There is no second opinion from another model while the switch is on. Doubtful answers go
  to the red list instead.
