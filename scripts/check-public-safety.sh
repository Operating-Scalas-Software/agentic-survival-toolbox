#!/usr/bin/env bash
set -euo pipefail

# Public-safety guard for a public repository.
#
# Scans every file Git tracks (plus untracked, non-ignored files) for strings
# that must never be committed here: internal project names, AWS account IDs and
# ARNs, access-key IDs, and private-key blocks.
#
# The patterns below are assembled from fragments so this script does not itself
# contain the literal internal strings it is meant to catch.

proj_a="zoo"       # + "rl" -> internal project codename (never write it out)
org_a="Operating"  # + "Scalas" -> organization name (never write it out)
org_b="Scalas"

pattern="(${proj_a}rl|${org_a}[-_. ]*${org_b}|[0-9]{12}|AKIA[0-9A-Z]{16}|arn:aws:[a-z0-9-]+:[a-z0-9-]+:[0-9]{12}|-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----)"

fails=0
while IFS= read -r -d '' f; do
  case "$f" in
    scripts/check-public-safety.sh) continue ;;
  esac
  [ -f "$f" ] || continue
  while IFS= read -r hit; do
    lineno="${hit%%:*}"
    text="${hit#*:}"
    printf 'FAIL %s:%s %s\n' "$f" "$lineno" "$text"
    fails=$((fails + 1))
  done < <(grep -nEi "$pattern" "$f" || true)
done < <(git ls-files -z --cached --others --exclude-standard)

if [ "$fails" -ne 0 ]; then
  printf 'check-public-safety: %d private/sensitive match(es) found - blocking.\n' "$fails" >&2
  exit 1
fi
printf 'check-public-safety: clean\n'
