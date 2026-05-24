# C005 Transaction Critic Plan

C005 turns the harness into a compact coding-agent CLI loop instead of a one-tool toy loop.

## Core loop

1. The actor returns a `transaction` containing plan/debug/decision updates plus ordered tool steps.
2. Runtime executes steps sequentially and stops the transaction on the first failed shell step.
3. Failed public/self-checks require `reflect` before repair.
4. Finish first passes deterministic hard gates.
5. Non-simple tasks then pass a semantic Gemini critic that judges whether the visible evidence actually supports completion.

## Durable per-trial artifacts

Each trace writes:

- `agent/trace-code/PLAN.md`
- `agent/trace-code/DEBUG.md`
- `agent/trace-code/DECISION_LOG.md`
- existing `ledger.jsonl`, state snapshots, observations, replay script, ATIF trajectory

## Boundaries

C005 does not consume hidden Harbor verifier failures inside a live trajectory. Hidden verifier results remain meta-harness development feedback only.
