# Screenshots

These images are for the docs pages to embed. `npm run screenshots`, from `web/`, makes all of them again. The UI shots come from the web UI in fixture mode at a 1440 by 900 viewport, with the API fixtures in `tests/fixtures/api/`. They show the `parley` suite, its question set and policy, and runs `0001` to `0004`. The UI is dark only. The CLI shots draw a command and its output as a terminal, 1100 pixels wide.

From a page in `docs/`, embed an image like this:

```markdown
![The Compare view, with two targets' answers side by side](images/compare.png)
```

From a page in `docs/reference/`, use `../images/compare.png`.

| Image | What it shows |
|---|---|
| `compare.png` | The Compare view. The `goblin-bribe` case is open as a full request with three questions, and the answers from `decision-1@foundry` and `clef-flash@workers-ai` are side by side, with the expected answers tagged, a probability heat ramp, and the spread between targets. |
| `targets.png` | The Targets view after a health check: 4 of 8 targets ready, why each other target is down, and each target's credentials, capabilities, limits, and cost. |
| `suite.png` | The `parley` suite: its cases, each case's expected answers, a draft case, and the Start run button. |
| `runs.png` | The run list: each run's suite, question set version, targets, status, progress, cost, and start time. Run `0003` is a probe run, and run `0004` was cancelled. |
| `run-in-progress.png` | Run `0002` while it runs: the progress bar at 8 of 12 jobs, with sent, cached, and skipped counts, and the Cancel button. |
| `run-report.png` | Run `0002` when it's finished, as a full-page shot (1440 by 1189): the metrics grid, decisions under the `parley` policy, the confusion matrix, calibration, and the answers that changed from baseline run `0001`, with McNemar's test. |
| `changes.png` | Stepping through changes: case `gnoll-watch` in run `0001` and run `0002`, side by side for each target. |
| `question-set.png` | The `parley` question set editor: its questions, the wording checks, and its versions. |
| `question-set-diff.png` | Two versions of the `parley` question set compared word by word. The newer one adds the `wait` option. |
| `policy-sweep.png` | The `parley` policy: its YAML, and a sweep of the `goodwill` threshold on run `0002` that plots decided and error rates. |
| `probe-report.png` | Probe run `0003`: how often each case's answer changed under each variant (option order, JSON key order, bare-number levels) for each target. |
| `cli-targets-list.png` | `jevtester targets list`: each configured target, unchecked, with its warnings. It reads the config only and asks no target anything. |
| `cli-report.png` | `jevtester report 0002`: run `0002`'s Markdown report, with its targets, metrics for each question, decisions, and changes from run `0001`. |
