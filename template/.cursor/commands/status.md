---
description: "Show the current state of the spec graph — ready, in-flight, blocked, drafting."
argument-hint: "FR-XXXX (optional)"
---
<!-- Generated from .agent-team/commands/status.md — do not edit by hand. -->

Run `python3 scripts/agent-status.py` to surface the current state of the spec graph.

If `{{args}}` is an FR ID, run `python3 scripts/agent-status.py --fr {{args}}` and report:
- Title, status, owner, dependencies
- Recent escalations against this FR
- Whether it's safe to pick up (i.e. not already `in-progress` by another agent)

Otherwise, run `python3 scripts/agent-status.py --all` and group the output by status:
- **Ready to pick up** (`status: ready`, no dependencies blocked)
- **In flight** (`in-progress`, `in-review`) -- name the agent or PR if known
- **Blocked** (`blocked`) -- link to the escalation
- **Drafting** (`draft`) -- Architect is still writing

End with a one-line recommendation: "Suggested next action: `/developer FR-XXXX`" (the highest-priority unblocked ready FR), or note if everything is in flight or blocked.
