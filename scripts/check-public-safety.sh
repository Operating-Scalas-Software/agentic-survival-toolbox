#!/usr/bin/env bash
set -euo pipefail

# Public-safety guard for a public repository.
#
# Scans every file Git tracks (plus untracked, non-ignored files) for strings
# that must never be committed here: internal project/org identifiers, email
# addresses, AWS account IDs and ARNs, access-key IDs, and private-key blocks.
#
# The internal identifiers are decoded from hex at runtime so their readable form
# never appears in this public file. AWS account IDs are matched generically as
# standalone 12-digit numbers (word-bounded) rather than listed, which is broad
# by design: a bare 12-digit number in prose is blocked and must be reworded.

id1=$(printf '\x7a\x6f\x6f\x72\x6c')      # internal project codename
id2=$(printf '\x73\x63\x61\x6c\x61\x73')  # internal organization token

email='[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
acct='[0-9]{12}'
access_key='AKIA[0-9A-Z]{16}'
arn='arn:aws:[a-z0-9-]+:[a-z0-9-]+:[0-9]{12}'
key_block='-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'

pattern="(${id1}|${id2}|${email}|\b${acct}\b|\b${access_key}\b|${arn}\b|${key_block})"

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
