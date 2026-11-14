import threading
from dataclasses import replace
from pathlib import Path

from scripts.issue_pipeline.decisions import CheckResult, PrView
from scripts.issue_pipeline.github import GitHubError, MergeAttempt, RepoRef
from scripts.issue_pipeline.models import NEEDS_FIX, PENDING_CI, READY
from scripts.issue_pipeline.publisher import finalize_issue, submit
from scripts.issue_pipeline.scheduler import plan_audit
from scripts.issue_pipeline.state import StateStore


SHA = "a" * 40
BASE = "b" * 40


class FakeGit:
    def __init__(self, head=SHA, branch="feature/12-export", clean=True, files=None):
        self.head = head
        self.branch = branch
        self.clean = clean
        self.files = set() if files is None else set(files)
        self.pushed = []
        self.checkouts = []

    def rev_parse(self, _cwd, ref="HEAD"):
        return self.head

    def current_branch(self, _cwd):
        return self.branch

    def status_clean(self, _cwd):
        return self.clean

    def push(self, cwd, remote, branch):
        self.pushed.append((str(cwd), remote, branch))

    def diff_names(self, _base, _head):
        return set(self.files)

    def checkout(self, *_args):
        self.checkouts.append(_args)


class FakeHub:
    def __init__(self):
        self.repos = RepoRef("chatvector-ai/chatvector-ai", "fork/chatvector-ai", "fork")
        self.prs = {}
        self.required = ["Backend Tests"]
        self.created = []
        self.updated = []
        self.merges = []
        self.open_by_branch = {}
        self._lock = threading.Lock()
        self.fail_admin = False
        self.fail_kind = "review_required"
        self.flip_to_failure = False

    def resolve_repos(self):
        return self.repos

    def required_checks(self):
        return list(self.required) if self.required is not None else None

    def find_open_pr(self, _owner, branch):
        number = self.open_by_branch.get(branch)
        return None if number is None else self.get_pr(number)

    def get_pr(self, number):
        with self._lock:
            return self.prs[number]

    def create_pr(self, *, branch, title, body):
        self.created.append((branch, title, body))
        pr = _open_pr(50, head=SHA)
        with self._lock:
            self.prs[50] = pr
            self.open_by_branch[branch] = 50
        return pr

    def update_pr(self, number, *, title, body):
        self.updated.append((number, title, body))
        return self.get_pr(number)

    def merge(self, number, *, admin, sha, subject, body):
        with self._lock:
            self.merges.append({"number": number, "admin": admin, "sha": sha, "subject": subject, "body": body})
            if not admin and self.fail_admin:
                if self.flip_to_failure:
                    current = self.prs[number]
                    self.prs[number] = replace(
                        current,
                        checks=(CheckResult("Backend Tests", "failure", "https://ci.example/fail"),),
                        merge_state="UNSTABLE",
                    )
                raise GitHubError("review required" if self.fail_kind == "review_required" else "required status check failed", self.fail_kind)
            current = self.prs[number]
            merged = replace(current, state="MERGED", merge_sha=f"m{number}")
            self.prs[number] = merged
            for other_number, other in list(self.prs.items()):
                if other.state == "OPEN":
                    self.prs[other_number] = replace(other, base_sha="c" * 40)
            return MergeAttempt(True, merged.merge_sha, "", "")


def _open_pr(number, *, head=SHA, base=BASE, review="APPROVED", merge_state="CLEAN", checks=None) -> PrView:
    return PrView(
        number=number,
        state="OPEN",
        draft=False,
        head_sha=head,
        base_sha=base,
        base_ref="main",
        mergeable="MERGEABLE",
        merge_state=merge_state,
        review_decision=review,
        checks=checks if checks is not None else (CheckResult("Backend Tests", "success", "https://ci.example/ok"),),
        url=f"https://example.test/pull/{number}",
    )


def _ready_store(tmp_path: Path, *, mode="issue", key="12") -> tuple[StateStore, object]:
    store = StateStore(tmp_path / "state.json")
    if mode == "audit-fix":
        state = plan_audit("AUDIT-001", "docs/audits/report.md", "Fix metric")
        issue = state.issues["AUDIT-001"]
        issue.state = READY
        issue.review_verdict = "READY"
        issue.reviewed_sha = SHA
        issue.base_sha = BASE
        issue.head_sha = SHA
        issue.branch = "fix/audit-metric"
        issue.worktree = str(tmp_path / "wt")
        issue.findings = "none"
        issue.verification = "pytest passed"
        issue.title = "Fix metric"
        store.save(state)
        return store, issue
    from scripts.issue_pipeline.models import BatchState, IssueRecord

    state = BatchState(concurrency=3)
    state.issues[key] = IssueRecord(
        key=key,
        number=int(key),
        title="Add export",
        summary="Add export",
        state=READY,
        review_verdict="READY",
        reviewed_sha=SHA,
        base_sha=BASE,
        head_sha=SHA,
        branch="feature/12-export",
        worktree=str(tmp_path / "wt"),
        findings="none",
        verification="pytest passed",
        areas=["backend"],
    )
    store.save(state)
    return store, state.issues[key]


def test_submit_pushes_the_worktree_and_reuses_an_existing_pr(tmp_path):
    store, issue = _ready_store(tmp_path)
    git = FakeGit()
    hub = FakeHub()
    hub.prs[8] = _open_pr(8)
    hub.open_by_branch[issue.branch] = 8
    result = submit(store, git, hub, "12")
    assert result["created"] is False
    assert result["pr"] == 8
    assert hub.created == []
    assert hub.updated[0][0] == 8
    assert git.pushed[0][0] == issue.worktree
    assert git.checkouts == []
    assert "checkout" not in git.pushed[0][2]
    saved = store.load().issues["12"]
    assert saved.state == PENDING_CI
    assert saved.pushed_sha == SHA


def test_submit_rejects_a_dirty_or_unreviewed_tree(tmp_path):
    store, _issue = _ready_store(tmp_path)
    try:
        submit(store, FakeGit(clean=False), FakeHub(), "12")
    except Exception as exc:
        assert "clean" in str(exc)
    else:
        raise AssertionError("dirty tree was published")
    assert store.load().issues["12"].state == READY
    try:
        submit(store, FakeGit(head="d" * 40), FakeHub(), "12")
    except Exception as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("unreviewed SHA was published")


def test_audit_fix_submit_creates_a_pr_without_closes(tmp_path):
    store, issue = _ready_store(tmp_path, mode="audit-fix")
    git = FakeGit(branch=issue.branch)
    hub = FakeHub()
    result = submit(store, git, hub, "AUDIT-001")
    assert result["created"] is True
    assert "Closes #" not in hub.created[0][2]
    assert "AUDIT-001" in hub.created[0][2]


def test_failed_ci_schedules_a_rereview_and_keeps_the_pr(tmp_path):
    store, _issue = _ready_store(tmp_path)
    saved = store.load()
    saved.issues["12"].state = PENDING_CI
    saved.issues["12"].pr_number = 8
    store.save(saved)
    hub = FakeHub()
    hub.prs[8] = _open_pr(8, checks=(CheckResult("Backend Tests", "failure", "https://ci.example/fail"),))
    result = finalize_issue(store, FakeGit(), hub, "12", lock_path=tmp_path / "merge.lock")
    assert result["action"] == "needs-fix"
    assert hub.merges == []
    issue = store.load().issues["12"]
    assert issue.state == NEEDS_FIX
    assert issue.pr_number == 8
    assert issue.reviewed_sha is None
    assert issue.correction_kind == "implement"
    assert issue.ci_failures[0]["url"] == "https://ci.example/fail"


def test_pending_and_missing_checks_do_not_merge(tmp_path):
    store, _issue = _ready_store(tmp_path)
    saved = store.load()
    saved.issues["12"].state = PENDING_CI
    saved.issues["12"].pr_number = 8
    store.save(saved)
    hub = FakeHub()
    hub.prs[8] = _open_pr(8, checks=(CheckResult("Backend Tests", "pending"),))
    pending = finalize_issue(store, FakeGit(), hub, "12", lock_path=tmp_path / "merge.lock")
    assert pending["action"] == "wait"
    assert store.load().issues["12"].state == PENDING_CI
    hub.prs[8] = _open_pr(8, checks=())
    hub.required = ["Backend Tests", "Frontend Validation"]
    missing = finalize_issue(store, FakeGit(), hub, "12", lock_path=tmp_path / "merge.lock")
    assert missing["action"] == "wait"
    assert "missing" in missing["reason"]
    assert hub.merges == []


def test_head_change_matching_the_worktree_requires_review_only(tmp_path):
    store, _issue = _ready_store(tmp_path)
    saved = store.load()
    saved.issues["12"].state = PENDING_CI
    saved.issues["12"].pr_number = 8
    store.save(saved)
    remote = "c" * 40
    hub = FakeHub()
    hub.prs[8] = _open_pr(8, head=remote, review="REVIEW_REQUIRED", merge_state="BLOCKED")
    result = finalize_issue(store, FakeGit(head=remote), hub, "12", lock_path=tmp_path / "merge.lock")
    assert result["action"] == "invalidate-head"
    issue = store.load().issues["12"]
    assert issue.state == NEEDS_FIX
    assert issue.correction_kind == "review-only"
    assert hub.merges == []


def test_diverged_head_blocks_without_resetting(tmp_path):
    store, _issue = _ready_store(tmp_path)
    saved = store.load()
    saved.issues["12"].state = PENDING_CI
    saved.issues["12"].pr_number = 8
    store.save(saved)
    hub = FakeHub()
    hub.prs[8] = _open_pr(8, head="c" * 40)
    finalize_issue(store, FakeGit(head=SHA), hub, "12", lock_path=tmp_path / "merge.lock")
    issue = store.load().issues["12"]
    assert issue.state == "blocked"
    assert issue.reason_code == "head-diverged"
    assert hub.merges == []


def test_admin_merge_retries_only_after_a_fresh_review_check(tmp_path):
    store, _issue = _ready_store(tmp_path)
    saved = store.load()
    saved.issues["12"].state = PENDING_CI
    saved.issues["12"].pr_number = 8
    store.save(saved)
    hub = FakeHub()
    hub.fail_admin = True
    hub.prs[8] = _open_pr(8, review="REVIEW_REQUIRED", merge_state="BLOCKED")
    result = finalize_issue(store, FakeGit(), hub, "12", lock_path=tmp_path / "merge.lock")
    assert result["action"] == "merged"
    assert result["merge_method"] == "admin-review-bypass"
    assert [call["admin"] for call in hub.merges] == [False, True]
    assert "Closes #12" in hub.merges[-1]["body"]


def test_admin_is_not_used_when_checks_fail_before_the_retry(tmp_path):
    store, _issue = _ready_store(tmp_path)
    saved = store.load()
    saved.issues["12"].state = PENDING_CI
    saved.issues["12"].pr_number = 8
    store.save(saved)
    hub = FakeHub()
    hub.fail_admin = True
    hub.flip_to_failure = True
    hub.prs[8] = _open_pr(8, review="REVIEW_REQUIRED", merge_state="BLOCKED")
    result = finalize_issue(store, FakeGit(), hub, "12", lock_path=tmp_path / "merge.lock")
    assert result["action"] == "needs-fix"
    assert [call["admin"] for call in hub.merges] == [False]
    assert store.load().issues["12"].state == NEEDS_FIX


def test_concurrent_merges_cannot_overlap_and_the_second_sees_the_new_base(tmp_path):
    from scripts.issue_pipeline.models import BatchState, IssueRecord

    state = BatchState(concurrency=3)
    for number in (1, 2):
        state.issues[str(number)] = IssueRecord(
            key=str(number),
            number=number,
            title=f"Issue {number}",
            summary=f"Issue {number}",
            state=PENDING_CI,
            review_verdict="READY",
            reviewed_sha=SHA,
            base_sha=BASE,
            head_sha=SHA,
            branch=f"feature/{number}",
            worktree=str(tmp_path / f"wt{number}"),
            pr_number=number,
            findings="none",
            verification="pytest passed",
            areas=["backend"],
        )
    store = StateStore(tmp_path / "state.json")
    store.save(state)
    hub = FakeHub()
    hub.prs[1] = _open_pr(1)
    hub.prs[2] = _open_pr(2)
    lock = tmp_path / "merge.lock"
    barrier = threading.Barrier(2)
    results = {}

    def run(number):
        barrier.wait()
        results[number] = finalize_issue(store, FakeGit(), hub, str(number), lock_path=lock)

    threads = [threading.Thread(target=run, args=(number,)) for number in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    merged = [number for number, result in results.items() if result["action"] == "merged"]
    assert len(merged) == 1
    assert len(hub.merges) == 1
    other = 2 if merged[0] == 1 else 1
    assert store.load().issues[str(other)].state == PENDING_CI
    assert store.load().issues[str(other)].reason_code == "needs-revalidation"
