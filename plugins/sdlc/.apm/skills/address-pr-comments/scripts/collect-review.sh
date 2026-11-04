#!/usr/bin/env bash
# Collect the review feedback of a GitHub pull request in a triage-ready form.
#
# Read-only. Prints a compact summary and stores the raw GraphQL response, so
# the thread ids needed by `addPullRequestReviewThreadReply` / `resolveReviewThread`
# are available without a second round trip.
#
# Usage: collect-review.sh [PR number]     (default: the PR of the current branch)
set -euo pipefail

pr=${1:-$(gh pr view --json number --jq .number)}
owner=$(gh repo view --json owner --jq .owner.login)
repo=$(gh repo view --json name --jq .name)
out=$(mktemp "${TMPDIR:-/tmp}/pr-review-XXXXXX.json")

gh api graphql -f query='
query($owner:String!,$repo:String!,$pr:Int!){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$pr){
      number title state headRefName
      reviewThreads(first:100){
        pageInfo { hasNextPage }
        nodes{
          id isResolved isOutdated path line
          comments(first:50){ nodes{ author{login} body createdAt } }
        }
      }
      reviews(first:50){ pageInfo { hasNextPage } nodes{ author{login} state body } }
      comments(first:50){ pageInfo { hasNextPage } nodes{ author{login} body } }
    }
  }
}' -F owner="$owner" -F repo="$repo" -F pr="$pr" >"$out"
chmod 600 "$out"

jq -r '
  def flat: gsub("\\s+"; " ") | .[0:220];
  def truncated(what; conn):
    if (conn.pageInfo.hasNextPage // false) then "WARNING: \(what) was truncated (first page only)" else empty end;
  .data.repository.pullRequest |
  "PR #\(.number) \(.title) [\(.state)] head=\(.headRefName)",
  "threads=\(.reviewThreads.nodes|length) unresolved=\([.reviewThreads.nodes[]|select(.isResolved==false)]|length)",
  truncated("review threads"; .reviewThreads),
  truncated("reviews"; .reviews),
  truncated("comments"; .comments),
  "",
  "UNRESOLVED THREADS",
  ([.reviewThreads.nodes[] | select(.isResolved==false)
    | "\(.id)\t\(.path // "-"):\(.line // "-")\(if .isOutdated then " (outdated)" else "" end)\t[\(.comments.nodes[0].author.login)]",
      "  \(.comments.nodes[0].body | flat)",
      ""] | join("\n")),
  "REVIEW SUMMARIES",
  ([.reviews.nodes[] | select((.body // "") != "")
    | "\(.author.login) \(.state): \(.body | flat)"] | join("\n")),
  "",
  "ISSUE COMMENTS",
  ([.comments.nodes[] | "[\(.author.login)] \(.body | flat)"] | join("\n")),
  "",
  "raw: \($raw)"
' --arg raw "$out" "$out"
