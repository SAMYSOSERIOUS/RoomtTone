#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
python -m roomtone.collect --simulate --hours 72
python -m roomtone.pipeline
echo "Now run: streamlit run roomtone/dashboard.py"
