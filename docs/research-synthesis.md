# Research Synthesis

## Decision

Build a direct-Gemini Terminal-Bench agent and optimize the harness around it.

The core stack is:

- Terminal-Bench v2 / Harbor for official task execution and scoring.
- Gemini `gemini-3.5-flash` via direct API calls.
- A custom Harbor-compatible agent instead of `gemini-cli`.
- Meta-Harness-style outer-loop search over harness code, prompts, observation policy, verification policy, and trace summarization.
- Flow-World-inspired trace-as-code artifacts only; no Flow World engine/runtime dependency.
- Ralph/oh-my-codex-inspired loop discipline: state ledgers, verification gates, critic review, stop conditions, and durable evidence.

## Ground truth from our smoke tests

### Appzilla runner

Verified locally on Appzilla:

- `/srv/appzilla` has enough disk for benchmark runs.
- Docker is active.
- `runsc`/gVisor exists.
- Harbor `0.8.0` and `terminal-bench 0.2.18` are installed in the Appzilla venv.
- Harbor can run an oracle smoke once Docker Compose compatibility is shimmed.
- Docker Compose user-defined network DNS fails under current Appzilla/Tailscale DNS; a Compose overlay with `network_mode: bridge` fixes container DNS for agent installation.

### Gemini path

Direct API works:

- `models` includes `models/gemini-3.5-flash`.
- `generateContent` to `gemini-3.5-flash` returned `ok`.

`gemini-cli` is not the primary path:

- It installed and reached Gemini after DNS was fixed.
- It then got stuck in undesirable CLI tool behavior: workspace glob outside the task, web-search invocation, and repeated Gemini API 500 retries.
- That failure mode is harness noise, not evidence the model/key are bad.

## External research anchors

- Meta-Harness frames harness code as the optimization target: the paper describes an outer-loop system that searches over harness code and gives a proposer filesystem access to prior source, scores, and execution traces. The reported TerminalBench-2 result is exactly the benchmark class we care about. Source: <https://arxiv.org/abs/2603.28052>.
- Terminal-Bench is a command-line benchmark where agents must solve realistic tasks inside terminal environments. Source: <https://www.tbench.ai/> and <https://arxiv.org/abs/2601.11868>.
- Harbor is the runner layer we already have installed and should treat as the compatibility target. Source: <https://harborframework.com/>.
- Flow World v2 is only a design inspiration for compact, analyzable traces. We are not importing or depending on its engine. Source: <https://github.com/phantastic-ai/flow-world-v2>.
- oh-my-codex skills show useful workflow primitives for our harness discipline: Ralph-style persistence and verification, durable goal/ledger artifacts, team/critic separation, and explicit cancellation/stop states. Source: <https://github.com/Yeachan-Heo/oh-my-codex>.

## Architecture bet

The right implementation surface is a custom agent because it lets us control:

1. The exact Gemini API call and retry policy.
2. The terminal action schema.
3. Prompt/observation shaping.
4. Trace emission.
5. Redaction and no-secret audit.
6. Meta-Harness candidate diffs.

A CLI wrapper hides too much state and can introduce tool behaviors we did not ask for. For this benchmark, inspectability beats convenience.

## Candidate ladder

- `C000_baseline`: direct Gemini, strict shell/finish JSON, conservative budgets, JSONL trace.
- `C001_env_bootstrap`: stronger initial environment snapshot and task classification.
- `C002_observation_policy`: head/tail truncation, file-tree summarizer, command-result compression.
- `C003_critic_gate`: pre-finish checklist and no-progress loop detector.
- `C004_public_verify_loop`: stronger public-test repair discipline.
- `C005_meta_candidate`: first outer-loop-proposed diff based on prior traces.

Each candidate must be general. It may not hardcode task IDs, known answers, Terminal-Bench repo facts, or hidden verifier behavior.

## n=5 smoke purpose

The n=5 run is not a leaderboard claim. It is a harness diagnostic panel.

Success means:

- all five trials complete with valid Harbor results;
- all five produce trace bundles;
- no secrets leak;
- failure causes are understandable from traces;
- at least one or two passes show the loop can actually solve tasks.

If it gets 0/5 but traces are clean, the next fix is harness loop quality. If traces are missing or invalid, the next fix is instrumentation, not prompt tuning.
