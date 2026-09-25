#!/usr/bin/env bash
# Hourly live run: collect one hour from each source you have access to, rebuild everything.
# Put it in cron:  0 * * * *  /path/to/roomtone/scripts/run_live.sh
set -e
cd "$(dirname "$0")/.."
python -m roomtone.collect --hours 1 --source bluesky                       # free, no key
[ -n "$REDDIT_ID" ]   && python -m roomtone.collect --hours 1 --source reddit   || true
[ -n "$YOUTUBE_KEY" ] && python -m roomtone.collect --hours 1 --source youtube  || true
python -m roomtone.collect --hours 1 --source mastodon || true
python -m roomtone.pipeline bluesky mastodon reddit youtube
python -m roomtone.rt_export
