# Terminal-Bench Submission Notes

Current submission routes:

1. T-Bench docs route for `terminal-bench-core==0.1.1`:
   - run compliant eval with default agent/test timeouts
   - contact maintainers listed in T-Bench docs

2. Harbor/TB2 leaderboard route:
   - open a PR to `harborframework/terminal-bench-2-leaderboard`
   - add files under:

```text
submissions/
  terminal-bench/
    2.0/
      <agent>__<model>/
        metadata.yaml
        <job-folder>/
          config.json
          <trial-1>/result.json
          <trial-2>/result.json
```

Before final submission, confirm whether target is TB2.0, TB2.1, or terminal-bench-core.
