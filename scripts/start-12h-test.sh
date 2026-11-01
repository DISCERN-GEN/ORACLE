#!/usr/bin/env bash
set -euo pipefail
cat >&2 <<'EOF'
ORACLE 12-hour autonomous acceptance test is LOCKED in this working build.
Do not start an acceptance run until all pre-flight gates in
`docs/12_HOUR_TEST_PROTOCOL.md` have been implemented and independently verified.
This build is not yet an autonomous dummy-test candidate.
EOF
exit 3
