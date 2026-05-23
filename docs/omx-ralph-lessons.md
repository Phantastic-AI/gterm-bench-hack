# Ralph / oh-my-codex Lessons for the Harness

## What we inspected

We inspected the `Yeachan-Heo/oh-my-codex` skill set, especially:

- `ralph`: persistent completion loop with verification evidence and architect sign-off.
- `ultragoal`: durable goal artifacts and ledger-style execution over long-running objectives.
- `prometheus-strict`: planning-only critic/oracle synthesis before execution.
- `best-practice-research`: source-grounded research discipline and evidence separation.

Source repo: <https://github.com/Yeachan-Heo/oh-my-codex>.

## Transferable ideas

### 1. State machine, not vibes

The agent should always know which phase it is in:

```text
BOOTSTRAP -> UNDERSTAND -> PLAN -> ACT -> OBSERVE -> VERIFY -> REPAIR -> CRITIC_GATE -> FINISH
```

Repeated failures should move to `REPAIR` or `ABORT`, not another blind `ACT`.

### 2. Ledger as first-class context

A compact ledger should be shown back to Gemini every turn:

```json
{"phase":"UNDERSTAND","required_outputs":["/app/answer.txt"],"constraints":["must be executable"]}
{"phase":"ACT","command":"pytest -q","exit_code":1,"purpose":"public verification"}
{"phase":"REPAIR","hypothesis":"output path mismatch","next":"write /app/answer.txt"}
```

This is cheaper and more reliable than replaying full terminal history.

### 3. Verification before finish

Ralph's useful rule is: do not declare done because the model feels done. Declare done only after fresh evidence.

For Terminal-Bench this means:

- run the strongest public check available;
- verify required output files/paths exist;
- inspect exact requested formats;
- run a critic gate before `finish`;
- then let Harbor's hidden verifier score.

### 4. Stop conditions

Good agents stop deliberately.

Stop when:

- public checks pass and the checklist is clean;
- max model calls/steps/time is reached;
- the same no-progress loop repeats;
- API errors persist after bounded retries;
- sandbox/env is unrecoverable.

### 5. Critic gates

Before finish:

```text
- Did we create every required output path?
- Did we run the strongest available public check?
- Is the output format exact?
- Did we accidentally depend on hidden state?
- Did we modify forbidden files?
- Is there a background process that must remain alive?
```

After repeated failure:

```text
- Are we rerunning the same failing command?
- Did we inspect the actual tests/task files?
- Is package installation the real blocker?
- Should we switch implementation strategy?
```

## Non-transferable ideas

Do not embed oh-my-codex itself inside the benchmark agent. It is an orchestration inspiration, not a runtime dependency. The benchmark agent must remain small, inspectable, and Harbor-compatible.
