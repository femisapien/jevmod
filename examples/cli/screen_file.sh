#!/usr/bin/env bash
# Screen a text file, one message per line. Exit 0 = clean, 1 = at least one hit, 2 = error.
# Usage: screen_file.sh FILE [extra jevmod check flags: --topic ... --rule ... --threshold ...]
set -uo pipefail
FILE="${1:?usage: screen_file.sh FILE [jevmod check flags]}"
shift
[ -r "$FILE" ] || { echo "cannot read $FILE" >&2; exit 2; }

FILTER='
import json, sys
hits = 0
for line in sys.stdin:
    d = json.loads(line)
    if d["action"] != "none":
        hits += 1
        print("%-20s %.2f  %r" % (d["category"], d["probability"], d["text"][:90]))
print("%d hit(s)" % hits, file=sys.stderr)
sys.exit(1 if hits else 0)
'
jevmod check --json "$@" - < "$FILE" | python -c "$FILTER"
status=("${PIPESTATUS[@]}")
[ "${status[0]}" -eq 2 ] && exit 2
exit "${status[1]}"
