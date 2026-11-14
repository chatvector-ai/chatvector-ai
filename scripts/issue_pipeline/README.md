# Issue pipeline

Dependency-aware scheduler and deterministic pull-request publisher for the
local issue queue. Implementation and independent review stay in Cursor
agents. Push, CI, and squash merge are scripts.

The agent contract lives in `docs/prompts/batch-solve.md` (local, not pushed).
This file is the operator reference for the code under `scripts/issue_pipeline/`.

## Commands

From the main checkout:

The CLI prepends `backend/.venv/bin` and Homebrew `libpq` to `PATH` when present
so `tick` and auto-revalidate can find `pytest` and `psql`. Set
`PIPELINE_SKIP_PATH_BOOTSTRAP=1` to disable.

```bash
scripts/issue-pipeline prepare --queue-file queue.txt --fetch
scripts/issue-pipeline next
scripts/issue-pipeline claim --issue 625 --action implement
scripts/issue-pipeline worktree-add --issue 625
scripts/issue-pipeline handoff --issue 625 --kind implement --file handoff.txt
scripts/issue-pipeline submit --issue 625
scripts/issue-pipeline tick
scripts/issue-pipeline poll-ci
scripts/issue-pipeline record-integration --issue 625 --base <sha> --result pass
scripts/issue-pipeline cleanup --issue 625
scripts/issue-pipeline resume
scripts/issue-pipeline lock exec -- pytest backend/tests/ -q --tb=short
```

`prepare --fetch` reads GitHub for the queued issues, including epic children
and `blockedBy` links when the API allows it. `--snapshot snapshot.json` is
the offline equivalent. `prepare` refuses to overwrite an existing state file
unless `--replace` is set. A cycle, duplicate, or missing snapshot exits
non-zero and does not write state.

## Scheduling

Queue text:

```text
Concurrency: 3

625
626 (after 625)
627
```

`Concurrency: 1` is the sequential pipeline: the current issue keeps the only
slot through review, publish, and CI. `Concurrency: 3` (the default when the
header is omitted) allows three implementation or review workers. Pull
requests waiting on CI do not take a worker slot in that mode, so another
independent issue can start.

Hard dependencies come from queue annotations (`(after 625)`, `depends: 625`),
issue text (`Depends on #625`, `Blocked by`, `Requires`, `Builds on`), GitHub
blocked-by links, and an epic `## Batch order` section. A missing prerequisite
that is not in the batch and not already closed blocks that issue and anything
that depends on it. Cycles and duplicate numbers fail the batch.

Shared key files and phrases such as "may conflict with #N" are recorded as
soft conflicts. They do not delay the start. "Related to #N" and two issues
that merely mention the same subsystem are not dependencies.

Epic parents are expanded by `prepare`. Children listed under `## Child issues`
replace the parent. `## Batch order` chains those children. `499 no-expand`
keeps the parent.

## Worktrees

Each issue is branched from `upstream/main` in its own worktree:

```text
../chatvector-worktrees/issue-625
```

Override the directory with `PIPELINE_WORKTREE_ROOT`. The publisher pushes
with `git -C <worktree> push` and does not check out that branch in the main
checkout. `cleanup` runs only after the pull request is merged, the worktree
is clean, and no worker is still running.

## Publisher

`submit` checks the READY review, the worktree HEAD, the branch name, and a
clean tree, then pushes and creates or updates one open pull request.

`tick` / `finalize` re-reads the pull request inside a merge lock before
squash-merging. When a pull request needs disjoint upstream revalidation,
`tick` runs locked `pytest` in the issue worktree and records integration
automatically (disable with `PIPELINE_AUTO_REVALIDATE=0`). Override the command
with `PIPELINE_REVALIDATE_PYTEST` (shell-split string).

`poll-ci` calls `tick` on every issue in `pending-ci` until they merge, need
agent follow-up (`needs-fix`, `blocked`), or the wait budget expires. Defaults:
15s between polls (`PIPELINE_CI_POLL_INTERVAL`), 30 minutes max
(`PIPELINE_CI_POLL_MAX_WAIT`). Use this after `submit` when the batch has open
pull requests waiting on CI — including from a separate terminal if you step
away from the orchestrator chat.

`tick` merges only when all of these hold:

- the remote head is the reviewed SHA (`--match-head-commit`)
- required checks are known (ruleset, classic protection, or
  `PIPELINE_REQUIRED_CHECKS`) and every one succeeded for that SHA
- the pull request is open, not draft, and targets `main`
- the base has not moved in a way that overlaps the change, unless a fresh
  integration result was recorded for the new base
- GitHub reports the pull request mergeable

`--admin` is used only when a fresh read still shows that a missing human
approval is the only blocker. Failing, pending, missing, cancelled, or unknown
checks, a changed head, conflicts, and merge-queue results do not use
`--admin`. The script does not change branch protection.

A failed required check moves the issue to `needs-fix` and keeps the same pull
request. The next correction goes through implementation and a new independent
review before `submit` pushes again. The fix budget defaults to 2
(`PIPELINE_MAX_FIX_ROUNDS`). Past that, the issue is `blocked` and other
issues continue.

## Resume

State is `.chatvector/issue-pipeline/state.json` (override with
`PIPELINE_STATE_PATH`). Every transition is written under a file lock, with a
short event log. After a crash, `resume` clears dead claims and records a
pull request that GitHub already merged. Run `resume` only when no worker
from this batch is still running. Do not start a second orchestrator against
the same state file.

## Resource limits

| Limit                                     | Default                                             |
| ----------------------------------------- | --------------------------------------------------- |
| Active implement/review workers           | 3 (`Concurrency:` or `PIPELINE_MAX_ACTIVE`, max 32) |
| Full local test suite / Docker test stack | 1, via `lock exec`                                  |
| Merges                                    | 1 at a time                                         |
| Fix rounds                                | 2                                                   |

`PIPELINE_FORCE_SEQUENTIAL=1` forces one-at-a-time execution and records
`fallback: sequential` on the batch. It does not drop dependencies.

## Tests

```bash
make pipeline-tests
```

The tests use temporary git repositories and fake GitHub responses. They do
not open pull requests or change repository settings.
