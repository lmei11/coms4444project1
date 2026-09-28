#!/usr/bin/env python3
"""Break down tournament.py's *_runs.csv by player identity - and by arena.

tournament.py's own standings average each code over *every* match it
appeared in, which flattens capacity and budget together. Once your config's
grid has more than one capacity or budget, that flat average hides whether a
player is good in general or just good in the settings that happen to
dominate the run count. This groups by whichever arena dimensions your grid
actually varies (capacity, budget, unit, days - whatever you've put in the
grid), so you can see standings shift as those change.

Each run's ``arena`` column is a label like "C28 u4 730d $120" or
"C28 u4 730d unlimited" (tournament.py's Arena.label). This parses that
string back into its components rather than assuming a fixed set of grid
keys, so it keeps working if you add or drop dimensions from the grid.

Usage:
    # auto: groups by whatever arena fields actually vary in the data
    python analyze_embarrassment.py results/player_id_comparison_runs.csv

    # force a specific breakdown
    python analyze_embarrassment.py results/..._runs.csv --by capacity
    python analyze_embarrassment.py results/..._runs.csv --by budget
    python analyze_embarrassment.py results/..._runs.csv --by capacity budget
    python analyze_embarrassment.py results/..._runs.csv --by arena   # every cell separately
    python analyze_embarrassment.py results/..._runs.csv --by none    # everything pooled together

    # restrict to one slice, e.g. only the $120 arenas
    python analyze_embarrassment.py results/..._runs.csv --filter budget=120
"""

import argparse
import csv
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ARENA_RE = re.compile(r'^C(?P<capacity>\d+) u(?P<unit>\d+) (?P<days>\d+)d (?P<budget>.+)$')
ALL_FIELDS = ('capacity', 'unit', 'days', 'budget')


def parse_arena(label: str) -> dict:
	match = ARENA_RE.match(label)
	if not match:
		raise ValueError(f"couldn't parse arena label: {label!r}")
	parts = match.groupdict()
	budget = parts['budget']
	return {
		'capacity': int(parts['capacity']),
		'unit': int(parts['unit']),
		'days': int(parts['days']),
		'budget': 'unlimited' if budget == 'unlimited' else budget.lstrip('$'),
	}


def load_rows(path: Path) -> list[dict]:
	with path.open(newline='') as fh:
		rows = list(csv.DictReader(fh))
	for row in rows:
		row['_arena'] = parse_arena(row['arena'])
	return rows


def varying_fields(rows: list[dict]) -> tuple[str, ...]:
	"""Which arena dimensions actually differ across the data."""
	distinct = {f: {row['_arena'][f] for row in rows} for f in ALL_FIELDS}
	return tuple(f for f in ALL_FIELDS if len(distinct[f]) > 1)


def apply_filter(rows: list[dict], filters: list[str]) -> list[dict]:
	for raw in filters:
		if '=' not in raw:
			raise SystemExit(f"--filter expects field=value, got {raw!r}")
		field, value = raw.split('=', 1)
		field = field.strip()
		if field not in ALL_FIELDS:
			raise SystemExit(f"--filter field must be one of {ALL_FIELDS}, got {field!r}")
		value = value.strip().lstrip('$')
		rows = [r for r in rows if str(r['_arena'][field]).lstrip('$') == value]
	if not rows:
		raise SystemExit('no runs left after applying --filter')
	return rows


def summarise(values: list[float]) -> dict:
	if not values:
		return {'n': 0, 'mean': None, 'median': None, 'stddev': None}
	return {
		'n': len(values),
		'mean': statistics.fmean(values),
		'median': statistics.median(values),
		'stddev': statistics.stdev(values) if len(values) > 1 else 0.0,
	}


def per_code_table(rows: list[dict]) -> list[dict]:
	overall: dict[str, list[float]] = defaultdict(list)
	solo: dict[str, list[float]] = defaultdict(list)
	mixed: dict[str, list[float]] = defaultdict(list)
	sockless: dict[str, list[float]] = defaultdict(list)
	faults: dict[str, int] = defaultdict(int)

	for row in rows:
		code = row['code']
		roster = row['roster'].split('+')
		emb = float(row['mean_daily_embarrassment'])
		overall[code].append(emb)
		sockless[code].append(float(row['sockless_days']))
		faults[code] += int(row['faults'])
		(solo if len(set(roster)) == 1 else mixed)[code].append(emb)

	codes = sorted(overall, key=lambda c: (len(c), c))
	table = [
		{
			'code': code,
			'overall': summarise(overall[code]),
			'solo': summarise(solo[code]),
			'mixed': summarise(mixed[code]),
			'sockless_days_mean': statistics.fmean(sockless[code]) if sockless[code] else 0.0,
			'faults': faults[code],
		}
		for code in codes
	]
	table.sort(key=lambda r: r['overall']['mean'] if r['overall']['mean'] is not None else float('inf'))
	for i, row in enumerate(table, start=1):
		row['rank'] = i
	return table


def group_key_label(fields: tuple[str, ...], key: tuple) -> str:
	if not fields:
		return 'all settings combined'
	parts = []
	for f, v in zip(fields, key, strict=True):
		unit = {'capacity': 'C', 'unit': 'u', 'days': 'd', 'budget': '$'}.get(f, '')
		if f == 'budget' and v == 'unlimited':
			parts.append('unlimited budget')
		elif f == 'budget':
			parts.append(f'${v}')
		else:
			parts.append(f'{unit}{v}')
	return ', '.join(parts)


def print_table(title: str, table: list[dict]) -> None:
	print(f'\n=== {title} ===')
	print(
		f'{"#":>2}  {"id":<4}  {"overall/day":>16}  {"solo/day":>16}  '
		f'{"mixed/day":>16}  {"sockless":>9}  faults'
	)

	def fmt(stats: dict) -> str:
		if stats['n'] == 0:
			return f'{"n/a":>16}'
		return f'{stats["mean"]:>10,.1f} +/-{stats["stddev"]:>4,.0f}'

	for row in table:
		print(
			f'{row["rank"]:>2}  {row["code"]:<4}  {fmt(row["overall"]):>16}  '
			f'{fmt(row["solo"]):>16}  {fmt(row["mixed"]):>16}  '
			f'{row["sockless_days_mean"]:>9,.1f}  {row["faults"]:>6}'
		)


def main() -> None:
	parser = argparse.ArgumentParser(
		description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
	)
	parser.add_argument('runs_csv', type=Path, help="tournament.py's *_runs.csv output")
	parser.add_argument(
		'--by',
		nargs='+',
		choices=[*ALL_FIELDS, 'arena', 'none'],
		default=None,
		help="Which arena dimension(s) to break standings out by. 'arena' groups by the full "
		"cell (every capacity/budget/unit/days combination separately). 'none' pools "
		'everything into one table. Default: auto-detect whichever fields actually vary '
		'in this file.',
	)
	parser.add_argument(
		'--filter',
		nargs='+',
		default=[],
		metavar='FIELD=VALUE',
		help='Restrict to runs matching this arena field first, e.g. --filter budget=120 '
		'capacity=28. Applied before grouping.',
	)
	args = parser.parse_args()

	if not args.runs_csv.exists():
		raise SystemExit(f'no such file: {args.runs_csv}')

	rows = load_rows(args.runs_csv)
	if not rows:
		raise SystemExit('runs csv is empty')

	rows = apply_filter(rows, args.filter)

	if args.by is None:
		fields = varying_fields(rows)
		if not fields:
			print(
				'Only one arena setting present in this file - nothing to break out by.',
				file=sys.stderr,
			)
	elif args.by == ['none']:
		fields = ()
	elif args.by == ['arena']:
		fields = ALL_FIELDS
	else:
		fields = tuple(args.by)

	groups: dict[tuple, list[dict]] = defaultdict(list)
	for row in rows:
		key = tuple(row['_arena'][f] for f in fields)
		groups[key].append(row)

	for key in sorted(groups, key=lambda k: [str(v) for v in k]):
		title = group_key_label(fields, key)
		print_table(title, per_code_table(groups[key]))

	print(f'\n({len(rows)} total run-rows across {len(groups)} group(s))')
	print('overall/day = mean_daily_embarrassment averaged over every seat the identity held')
	print('within that group; solo/day = all-one-identity rosters only; mixed/day = rosters')
	print('with at least one different identity. Lower is better throughout.')


if __name__ == '__main__':
	main()