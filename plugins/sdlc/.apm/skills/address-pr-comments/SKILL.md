---
name: address-pr-comments
description: 'Work through GitHub pull request review feedback end to end: fetch every review thread and comment, implement each fix (or justify a deliberate deviation), verify with the repository checks, push, then reply to and resolve each thread. Use when asked to address/resolve/work through PR review comments or close review threads, e.g. "address the comments on PR #24", "work through the review feedback", "close the resolved review threads".'
argument-hint: '[PR number or URL] (default: the PR of the current branch)'
---

# Address PR comments

Turn a review on a pull request into a validated, pushed change set where every
thread is either fixed and closed, or explicitly reported as not addressed.

## Inputs

- PR number or URL. Default: `gh pr view --json number --jq .number`.
- Autonomy threshold. Default: act automatically at **≥ 80% confidence**,
  otherwise report and leave the thread open. Honour a different threshold if
  the request states one.

## Progress

- [ ] Preflight: PR metadata, repository rules, clean tree, PR head branch
- [ ] Collect feedback and list every unresolved thread
- [ ] Write a verdict and its evidence for each thread, before editing
- [ ] Implement, adding a test for each invariant the review asked to protect
- [ ] Local checks green, then commit and push
- [ ] CI green on the new head SHA
- [ ] Reply to every implemented thread, then resolve it
- [ ] Report the table; unresolved threads == declined threads

## Procedure

### 1. Preflight

- `gh auth status`; `gh pr view <n> --json number,title,state,headRefName,baseRefName,mergeable`.
- Read the repository's own rules **before** changing code — they define what
  "validated" means: `AGENTS.md`, `.github/copilot-instructions.md`,
  `README.md`, `CONTRIBUTING.md`.
- `git status --short`. Work on the PR head branch (check it out or use a
  worktree). Never commit to `main`, never force-push a reviewed branch.

### 2. Collect every piece of feedback

Run [the collection script](./scripts/collect-review.sh). It stores the raw
GraphQL response — thread ids included — and prints a triage-ready summary.
Invoke it from the directory that contains this `SKILL.md`:

```bash
bash <skill-dir>/scripts/collect-review.sh        # PR of the current branch
bash <skill-dir>/scripts/collect-review.sh 24     # explicit PR
```

Open the JSON file named on the `raw:` line of the summary only for a field the
summary omits; re-running the script after each push is cheaper than re-reading
the JSON.

Rules for triage scope:

- Only **unresolved** threads are work items; resolved ones are history. Read
  the whole thread before acting so you do not re-litigate a decision that was
  already settled in a reply.
- `isOutdated: true` means the diff moved. Re-check that the concern still
  applies to the current code before changing anything; if the code already
  fixed it, reply with that evidence and resolve.
- The review **summary body** counts as work items. Reviewers often repeat
  priorities there and add nits that have no inline thread.
- A comment that asks for something genuinely out of scope for this PR (a new
  platform decision, a redesign) is not silently declined: file a follow-up
  issue, link it in the reply, and leave the thread open unless the reviewer
  agrees to close it.
- Ignore non-actionable noise: bot quota failures, CI status, "Copilot was
  unable to review".
- Re-run collection after every push: a new commit can trigger a re-review and
  new threads.

### 3. Decide a verdict per thread

| Verdict | Action |
| --- | --- |
| **accept** | Implement exactly what was proposed. |
| **better** | Implement an alternative; the reply says why it is better. |
| **partial** | Implement what is possible and document the constraint (for example a GitHub Actions key that does not accept the `env` context). |
| **decline** | Change no code; reply with the reasoning; leave the thread **open**. |

Before editing anything, write one row per thread (see
[Report template](#report-template)) with the verdict and the evidence you will
check. That plan is what stops a comment from being silently dropped.

- Decide from evidence in the repository, not from memory: read the file, run
  the command, check the docs. Evidence means a passing local check, a command
  transcript, or a documentation quote — not "this should work".
- Below the confidence threshold: make no change, report it, leave it open.
- Verify empirical claims before replying — if a comment says an install flag
  is safe, actually run it in a throwaway directory and quote the result.
- One verdict per thread. Never resolve without a reply, never batch a "done".

### 4. Implement

- Group edits per file. Add tests that pin the invariant the reviewer asked for
  — a comment "this will drift" deserves a test that fails when it drifts.
- Update the docs the review touched (README, runbooks, agent instructions).
- Keep unrelated refactors out of the review-fix commit.

### 5. Validate locally

Run the repository's documented sequence (usually build → lint → format check →
tests → synth/package). All of it must pass **before** pushing; CI is not the
gate for review fixes.

### 6. Commit and push

One commit per review round; the message enumerates what each thread changed:

```text
ci(deploy): address PR #24 review feedback

- Extract the digest recipe into scripts/assembly-digest.sh (thread: duplication).
- Publish the digest as an artifact so #15 can verify promotion.
...
```

`git push` — never `--force`.

### 7. Wait for CI

```bash
gh run list --branch <branch> --limit 10 \
  --json name,status,conclusion,headSha,databaseId \
  --jq '.[] | "\(.name) \(.status) \(.conclusion // "-") \(.headSha[0:7]) \(.databaseId)"'
gh run watch <databaseId> --exit-status
```

Report the pushed head SHA and the conclusion of every workflow.

### 8. Reply and resolve

Reply first, then resolve — one line per thread, naming the fix and the short
SHA:

```bash
while IFS='|' read -r tid msg; do
  gh api graphql -f query='mutation($t:ID!,$b:String!){
    addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$t, body:$b}){ comment{ id } } }' \
    -f t="$tid" -f b="$msg" >/dev/null
  gh api graphql -f query='mutation($t:ID!){
    resolveReviewThread(input:{threadId:$t}){ thread{ isResolved } } }' \
    -f t="$tid" --jq '.data.resolveReviewThread.thread.isResolved'
done <<'EOF'
PRRT_kwDO…|Extracted to `scripts/assembly-digest.sh`, used by both jobs and asserted in tests. b1d645d
PRRT_kwDO…|Wording fixed in the workflow and README: pending runs are dropped, in-progress runs are not cancelled. b1d645d
EOF
```

- Resolve only threads whose fix is implemented (fully, or as a documented
  partial).
- Declined / below-threshold threads: reply with the reasoning, **leave them
  open**, and list them in the report.
- Verify closure:

```bash
gh api graphql -f query='query{
  repository(owner:"<owner>",name:"<repo>"){ pullRequest(number:<n>){
    reviewThreads(first:100){ nodes{ isResolved } } } } }' \
  --jq '[.data.repository.pullRequest.reviewThreads.nodes[]|select(.isResolved==false)]|length'
```

The unresolved count must equal the number of declined threads.

Then re-collect (step 2). If the push produced new threads, go back to step 3;
stop when the only unresolved threads are the declined ones. Two rounds is
typical — if a round produces no actionable change, stop and report instead of
looping.

### 9. Report

Fill the [report template](#report-template). Give a confidence percentage per
thread so the rows that need a human decision stand out, and state explicitly
when a thread was only partially addressed.

## Report template

| Thread | Verdict | What shipped | Confidence |
| --- | --- | --- | --- |
| `deploy.yml:46` — duplicated digest recipe | accept | Shared `scripts/assembly-digest.sh`, used by both jobs and pinned by a test | 95% |
| `deploy.yml:101` — `dev` literals | partial | Stage templated via `env: STAGE`; `environment:` and the concurrency group stay literal because they take no `env` context | 90% |
| `test/workflows.test.ts:13` — hardcoded filenames | decline | Out of scope here; follow-up filed as #25 | 60% |

Then state:

- **Deviations** — where you shipped something other than the proposal, and why.
- **Left open** — declined or below-threshold threads, with the reason.
- **CI** — workflow conclusions for the pushed head SHA.
- **PR state** — open, merged, or blocked.

## Gotchas

- Review **threads** exist only in GraphQL. The REST comments API returns
  comments without thread ids, so it cannot drive `resolveReviewThread`.
- `gh pr view --json comments` omits inline review comments; do not use it to
  inventory feedback.
- `reviewThreads` returns resolved threads too. Filter `isResolved == false`
  before treating anything as a work item, or you will reopen settled debates.
- `isOutdated` means the diff moved, not that the concern is void.
- A review summary body has no thread id. Answer it with one top-level PR
  comment (`gh pr comment`) that covers each non-inline point; do not hijack an
  unrelated thread just to have somewhere to put the text.
- GitHub does not allow self-approval. A review submitted by the PR author
  appears as `COMMENTED` even when its text says "approve" — never report it as
  an approval.
- In `gh api graphql`, `-F pr=24` sends an integer; `-f pr=24` sends a string
  and the query fails on the `Int!` variable.
- When a reviewer asserts platform behaviour (which context a key accepts,
  whether a flag is safe), verify it. A "partial" verdict usually means the
  proposal assumed a capability that does not exist.
- Thread ids look like `PRRT_kwDO…`; keep the reply order identical to the
  report order so each reply can be traced to its row.

## Completion checks

- [ ] Every thread has a verdict; every implemented thread has a reply.
- [ ] Local checks green on the pushed commit.
- [ ] CI green on the pushed head SHA, or the failure is explained.
- [ ] Unresolved threads == declined threads, and both are listed in the report.
- [ ] Replies reference the commit SHA.
- [ ] The review-fix commit contains no unrelated changes.

## Anti-patterns

- Resolving a thread without a reply, or resolving one you declined.
- Blanket "thanks, done" replies; they hide partial work.
- Treating the review summary as optional because it has no inline thread.
- Pushing unverified changes just to satisfy a comment.
- Force-pushing over a reviewed branch, or rewriting commits already reviewed.
- Reporting "all threads addressed" when some were only partially addressed.
