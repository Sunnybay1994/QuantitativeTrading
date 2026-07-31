#!/usr/bin/env bash
set -eu

if [ "$#" -ne 1 ]; then
  exit 64
fi
session_date="$1"
case "$session_date" in
  2026-08-03|2026-08-04|2026-08-05|2026-08-06|2026-08-07) ;;
  *) exit 65 ;;
esac

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
log_root="artifacts/data_quality/m1_daily_streak/20260803_20260807"
mkdir -p "$log_root"
log_path="$log_root/$session_date.json"
set -C
: > "$log_path" || exit 66
set +C

tmp_path="$log_root/.$session_date.$$.tmp"
trap 'rm -f "$tmp_path"' EXIT
if /home/mabw/miniforge3/bin/conda run -n base \
  python -B -m quant.data.run_scheduled_daily \
  --date "$session_date" \
  --symbols 000001.SZ 600000.SH 00005.HK 00700.HK \
  --data-root data \
  --artifact-root artifacts >"$tmp_path" 2>/dev/null; then
  if [ "$(wc -l < "$tmp_path")" -eq 1 ]; then
    cp "$tmp_path" "$log_path"
    exit 0
  fi
fi
printf '%s\n' '{"status":"FAILED","code":"M1_SCHEDULE_PROCESS_FAILED"}' > "$log_path"
exit 2
