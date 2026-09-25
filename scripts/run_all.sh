#!/usr/bin/env bash
# One command from nothing to a running dashboard on practice data.
set -e
cd "$(dirname "$0")/.."
for s in bluesky mastodon reddit youtube; do python -m roomtone.collect --simulate --hours 72 --source $s; done
python -m roomtone.pipeline bluesky mastodon reddit youtube
python -m roomtone.rt_export
python tools/unpack_design.py design/Roomtone_Dashboard.html
echo
echo "Done. Open the dashboard:   cd app && python -m http.server 8080    ->  http://localhost:8080"
