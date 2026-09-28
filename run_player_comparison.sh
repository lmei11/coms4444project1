#!/usr/bin/env bash
# Compare player identities 1-10 (5 doesn't exist) head-to-head: every
# all-same-identity roster and every mixed 4-seat combination, at
# C=28 / unit=4 / 730 days / $120 budget.
#
# This is a thin wrapper around the repo's own tournament.py, which already
# does exactly this (build_matches uses combinations_with_replacement over
# the entrants, so "1111", "1234", "2223", etc. are all generated for you -
# there's no need for a separate script that enumerates rosters by hand).
#
# Usage (run from anywhere - it finds the repo root itself):
#   ./run_player_comparison.sh                 # calibrate, then run, then analyze
#   ./run_player_comparison.sh --skip-calibrate
#   ./run_player_comparison.sh --quick         # 1 seed, entrants 1-4 only, for a fast smoke test
#
# Extra args after these are passed straight through to tournament.py, e.g.:
#   ./run_player_comparison.sh --seeds 1 2 3 -- --workers 8

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_SRC="$SCRIPT_DIR/player_id_comparison.json"
ANALYZE_SRC="$SCRIPT_DIR/analyze_embarrassment.py"

# Find the repo root by walking up from wherever this script lives until
# tournament.py turns up, so it works whether you dropped this next to
# player.py, at the repo root, or anywhere in between.
find_repo_root() {
	local dir="$SCRIPT_DIR"
	while [[ "$dir" != "/" ]]; do
		if [[ -f "$dir/tournament.py" ]]; then
			echo "$dir"
			return 0
		fi
		dir="$(dirname "$dir")"
	done
	return 1
}

REPO_ROOT="$(find_repo_root)" || {
	echo "error: couldn't find tournament.py by walking up from $SCRIPT_DIR" >&2
	echo "       run this from inside the repo, or drop it into the repo root." >&2
	exit 1
}
echo "Repo root: $REPO_ROOT"
cd "$REPO_ROOT"

if [[ ! -f players/player_3/player.py ]]; then
	echo "error: players/player_3/player.py not found - swap in your Player3 code first." >&2
	exit 1
fi

RUN="python"
command -v uv >/dev/null 2>&1 && RUN="uv run python"

SKIP_CALIBRATE=0
QUICK=0
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
	case "$1" in
	--skip-calibrate)
		SKIP_CALIBRATE=1
		shift
		;;
	--quick)
		QUICK=1
		shift
		;;
	*)
		EXTRA_ARGS+=("$1")
		shift
		;;
	esac
done

mkdir -p configs results
if [[ "$QUICK" -eq 1 ]]; then
	CONFIG=configs/player_id_comparison_quick.json
	python3 - "$CONFIG_SRC" "$CONFIG" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
cfg = json.load(open(src))
cfg['name'] = 'player_id_comparison_quick'
cfg['entrants'] = ['1', '2', '3', '4']
cfg['seeds'] = [1]
json.dump(cfg, open(dst, 'w'), indent=2)
PY
	echo "Quick mode: entrants 1-4 only, 1 seed (35 matches, 35 runs)."
else
	CONFIG=configs/player_id_comparison.json
	cp "$CONFIG_SRC" "$CONFIG"
	echo "Full comparison: 9 entrants, 4 seats -> C(12,4) = 495 rosters x $(python3 -c "import json;print(len(json.load(open('$CONFIG'))['seeds']))") seeds."
	echo "At roughly 1s/run single-threaded, budget an hour or so; more CPU cores cut this a lot"
	echo "(tournament.py defaults to one worker per core - pass '-- --workers N' to control it)."
fi

if [[ "$SKIP_CALIBRATE" -eq 0 ]]; then
	echo
	echo "=== Calibrating: what does this field actually spend with no budget cap? ==="
	$RUN tournament.py "$CONFIG" --out-dir results --calibrate "${EXTRA_ARGS[@]}"
	echo
	echo "Compare the recommended figure above to this config's \$120 budget. If \$120 is"
	echo "far below it, the ranking below will mostly measure who runs out of socks first,"
	echo "not who matches better - both are valid things to study, just be clear which one"
	echo "you're looking at. Re-run with --skip-calibrate once you've decided on a budget."
	echo
	read -rp "Continue with the \$120 budget as configured? [y/N] " reply
	[[ "$reply" =~ ^[Yy]$ ]] || exit 0
fi

echo
echo "=== Running the tournament ==="
$RUN tournament.py "$CONFIG" --out-dir results "${EXTRA_ARGS[@]}"

RUNS_CSV="results/$(python3 -c "import json;print(json.load(open('$CONFIG'))['name'])")_runs.csv"

echo
echo "=== Embarrassment breakdown (solo vs. mixed rosters) ==="
python3 "$ANALYZE_SRC" "$RUNS_CSV"

echo
echo "Full detail:"
echo "  results/*_standings.csv   - tournament.py's own ranking (embarrassment, spend, sockless days)"
echo "  results/*_runs.csv        - one row per (match, seed, seat)"
echo "  results/*.json            - everything, including which rosters actually formed"
