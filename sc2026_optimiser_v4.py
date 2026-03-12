#!/usr/bin/env python3
"""
AFL SUPERCOACH 2026: OPTIMISER v4
=================================
- Dual objective: keepers (season-long) vs cash cows (capital growth)
- Position-specific keeper thresholds
- Monte Carlo confidence via projection perturbation
- Robustness analysis: near-misses and high-ownership omissions
"""
import json, csv, sys, random
from collections import defaultdict, Counter
from pulp import *

# =============================================================================
# 1. LOAD RAW DATA (R0 updated)
# =============================================================================
with open('AFL_supercoach_playerlist_2026_R0') as f:
    raw = json.load(f)

TEAM_BYES = {
    'ADE': 0, 'BRL': 2, 'CAR': 2, 'COL': 2, 'ESS': 0, 'FRE': 0,
    'GCS': 3, 'GEE': 2, 'GWS': 4, 'HAW': 3, 'MEL': 0, 'NTH': 0,
    'PTA': 0, 'RIC': 0, 'STK': 4, 'SYD': 3, 'WBD': 3, 'WCE': 0,
}
OPENING_ROUND_CLUBS = {'SYD','CAR','GCS','GEE','GWS','HAW','BRL','WBD','STK','COL'}
PRICE_CHANGE_PER_PT = 440
GAMES_WEIGHT_CAP = 0.80

# =============================================================================
# 2. LOAD CUSTOM PROJECTIONS
# =============================================================================
rookie_overrides = {}
with open('rookie_projections.csv') as f:
    for row in csv.DictReader(f):
        if row.get('exclude') == '1': continue
        try:
            avg = float(row['custom_avg'])
            if avg > 0: rookie_overrides[row['name']] = avg
        except: pass

midprice_overrides = {}
with open('midprice_projections.csv') as f:
    for row in csv.DictReader(f):
        try:
            avg = float(row['custom_avg'])
            if avg > 0: midprice_overrides[row['name']] = avg
        except: pass

custom_overrides = {**rookie_overrides, **midprice_overrides}

# Ruck rule-change overrides + manual
custom_overrides.update({
    'Max Gawn': 124, 'Tristan Xerri': 128, 'Brodie Grundy': 122,
    'Tim English': 114, 'Luke Jackson': 113, 'Tom De Koning': 100,
    'Darcy Cameron': 111, 'Nicholas Madden': 83, 'Lachlan McAndrew': 75,
    'Liam Reidy': 30, 'Rory Laird': 100, 'Rowan Marshall': 80,
})

# User spreadsheet overrides (post-R0 review)
custom_overrides.update({
    'Zak Butters': 120,
    'Bailey Smith': 113,
    'Nick Daicos': 116,
    'Errol Gulden': 108,
    'Sam Flanders': 103,
    'Christian Petracca': 108,
    'Darcy Parish': 100,
    'Sam Walsh': 100,
    'Clayton Oliver': 100,
    'George Hewett': 105,
    'Tanner Bruhn': 80,
    'Connor Budarick': 80,
})
print(f"Custom overrides: {len(custom_overrides)} players")

# =============================================================================
# 3. LOAD INJURY EXCLUSIONS
# =============================================================================
excluded_names = set()
with open('excluded_players.csv') as f:
    for row in csv.DictReader(f):
        excluded_names.add(row['name'])

# =============================================================================
# 4. BUILD PLAYER DATABASE (blended projections)
# =============================================================================
players = []
for p in raw:
    stats = p['player_stats'][0] if p['player_stats'] else {}
    if not stats or stats.get('price', 0) == 0: continue

    name = f"{p['first_name']} {p['last_name']}"
    positions = [pos['position'] for pos in p.get('positions', [])]
    team = p['team']['abbrev']
    price = stats['price']
    bye = TEAM_BYES.get(team, 0)
    games_in_3r = 2 if bye in (1, 2, 3, 4) else 3
    sc_season_games = 22.5 if team in OPENING_ROUND_CLUBS else 23.0

    prev_avg = p.get('previous_average', 0) or 0
    prev_games = p.get('previous_games', 0) or 0

    # SC Plus per-game projection: average of non-zero ppts rounds
    # (pavg3 includes bye-round zeros which corrupts the average)
    ppts1 = stats.get('ppts1', 0) or 0
    ppts2 = stats.get('ppts2', 0) or 0
    ppts3 = stats.get('ppts3', 0) or 0
    playing_ppts = [x for x in [ppts1, ppts2, ppts3] if x > 0]
    sc_per_game = sum(playing_ppts) / len(playing_ppts) if playing_ppts else 0

    if name in custom_overrides:
        proj_avg = custom_overrides[name]
        source = 'CUSTOM'
    else:
        gw = min(prev_games / 22.0, 1.0) * GAMES_WEIGHT_CAP
        if prev_avg > 0 and sc_per_game > 0:
            proj_avg = gw * prev_avg + (1 - gw) * sc_per_game
        elif prev_avg > 0:
            proj_avg = prev_avg
        elif sc_per_game > 0:
            proj_avg = sc_per_game
        else:
            proj_avg = 0
        source = 'BLENDED'

    be = price / 5400
    proj_rise = int((proj_avg - be) * PRICE_CHANGE_PER_PT * games_in_3r)

    # R0 actual score (if played)
    r0_score = stats.get('points', 0) or 0
    r0_games = stats.get('games', 0) or 0

    rec = {
        'name': name, 'team': team, 'positions': positions,
        'pos_str': '/'.join(positions), 'price': price,
        'prev_avg': prev_avg, 'prev_games': prev_games,
        'own': stats.get('own', 0) or 0,
        'sc_pavg3': sc_per_game,
        'proj_avg3': proj_avg, 'proj_rise': proj_rise,
        'bye': bye, 'games_3r': games_in_3r,
        'sc_season_games': sc_season_games,
        'r0_score': r0_score, 'r0_games': r0_games,
        'injury': p.get('injury_suspension_status'),
        'injury_text': p.get('injury_suspension_status_text') or '',
        'source': source,
    }
    players.append(rec)

print(f"Loaded {len(players)} players")

# =============================================================================
# 5. HARD CONSTRAINTS
# =============================================================================
MUST_HAVE = ['Tristan Xerri', 'Lachlan McAndrew', 'Liam Reidy', 'Brodie Grundy']
MUST_AVOID = ['Reilly O\'Brien', 'Adam Treloar', 'Hugh McCluggage']
for name in excluded_names:
    if name not in MUST_AVOID: MUST_AVOID.append(name)

# R1 team exclusions: CAR/RIC players not named in R1 team (except Reidy)
with open('r1_team_exclusions.txt') as f:
    for line in f:
        name = line.strip()
        if name and name not in MUST_AVOID:
            MUST_AVOID.append(name)
print(f"Total exclusions: {len(MUST_AVOID)} (injuries + R1 omissions)")

# =============================================================================
# 6. OPTIMISER WITH POSITION-SPECIFIC KEEPER THRESHOLDS
# =============================================================================
def get_primary_position(positions):
    """Return primary position for keeper threshold lookup."""
    for pos in ['RUC', 'MID', 'FWD', 'DEF']:
        if pos in positions: return pos
    return 'FWD'

def optimise_team(
    players,
    salary_cap=10_000_000,
    squad_size={'DEF': 8, 'MID': 11, 'RUC': 3, 'FWD': 8, 'FLX': 1},
    keeper_thresholds={'DEF': 90, 'MID': 100, 'RUC': 100, 'FWD': 90},
    cow_rounds=8,
    w_cow_rise=3.5,
    max_per_club=None,
    must_have=None, must_avoid=None,
    proj_noise=0.0,  # for Monte Carlo: std dev as fraction of avg
    label="OPTIMAL TEAM",
    quiet=False,
):
    eligible = [p for p in players if p['name'] not in (must_avoid or [])]
    if not quiet:
        print(f"\n{'='*140}")
        print(f"  {label}")
        print(f"  Keeper thresholds: {keeper_thresholds} | Cow: {cow_rounds}rd, rise_wt={w_cow_rise}")
        print(f"{'='*140}")

    n = len(eligible)
    pos_list = ['DEF', 'MID', 'RUC', 'FWD', 'FLX']

    prob = LpProblem("SC2026", LpMaximize)
    x = [LpVariable(f"x_{i}", cat='Binary') for i in range(n)]
    y = [[LpVariable(f"y_{i}_{j}", cat='Binary') for j in range(len(pos_list))] for i in range(n)]

    obj = []
    for i, p in enumerate(eligible):
        avg = p['proj_avg3']
        if proj_noise > 0:
            avg = max(0, avg + random.gauss(0, avg * proj_noise))

        sgm = p['sc_season_games']
        rise = p['proj_rise']
        primary_pos = get_primary_position(p['positions'])
        threshold = keeper_thresholds.get(primary_pos, 90)

        if avg >= threshold:
            val = avg * sgm
        else:
            val = avg * cow_rounds + w_cow_rise * (rise / 1000)
        obj.append(val)

    prob += lpSum(x[i] * obj[i] for i in range(n))
    prob += lpSum(x[i] * eligible[i]['price'] for i in range(n)) <= salary_cap

    for j, pos in enumerate(pos_list):
        prob += lpSum(y[i][j] for i in range(n)) == squad_size.get(pos, 0)
    for i in range(n):
        prob += lpSum(y[i][j] for j in range(len(pos_list))) == x[i]
    for i, p in enumerate(eligible):
        for j, pos in enumerate(pos_list):
            if pos != 'FLX' and pos not in p['positions']:
                prob += y[i][j] == 0
    if max_per_club:
        for club in set(p['team'] for p in eligible):
            idxs = [i for i, p in enumerate(eligible) if p['team'] == club]
            prob += lpSum(x[i] for i in idxs) <= max_per_club
    if must_have:
        for name in must_have:
            idx = next((i for i, p in enumerate(eligible) if p['name'] == name), None)
            if idx is not None: prob += x[idx] == 1

    prob.solve(PULP_CBC_CMD(msg=0))
    status = LpStatus[prob.status]
    if status != 'Optimal':
        return status, [], 0, 0, 0, 0

    selected = []
    for i, p in enumerate(eligible):
        if x[i].varValue and x[i].varValue > 0.5:
            apos = 'UNK'
            for j, pos in enumerate(pos_list):
                if y[i][j].varValue and y[i][j].varValue > 0.5:
                    apos = pos; break
            selected.append({**p, 'assigned_pos': apos, 'obj_value': obj[i]})

    sal = sum(p['price'] for p in selected)
    pts = sum(p['proj_total_3r'] for p in selected) if 'proj_total_3r' in selected[0] else 0
    rise = sum(p['proj_rise'] for p in selected)
    obj_total = sum(p['obj_value'] for p in selected)
    return status, selected, obj_total, sal, pts, rise


def print_team(selected, sal, pts, rise, obj_total, keeper_thresholds, label=""):
    pos_order = {'DEF': 0, 'MID': 1, 'RUC': 2, 'FWD': 3, 'FLX': 4}
    selected.sort(key=lambda p: (pos_order.get(p['assigned_pos'], 5), -p['price']))

    print(f"\n{'─'*160}")
    print(f"{'Pos':<5} {'Player':<26} {'NatPos':<10} {'Team':<5} {'Price':>10} {'Own%':>6} "
          f"{'Avg':>6} {'Type':<5} {'SeasonPts':>9} {'EarlyΔ':>9} {'R0':>4} {'Src':<7} {'EBye':>5}")
    print(f"{'─'*160}")

    pos_totals = defaultdict(lambda: {'n': 0, 'sal': 0, 'season_pts': 0, 'rise': 0})
    keepers, cows = [], []
    cur = None
    for p in selected:
        apos = p['assigned_pos']
        if apos != cur:
            if cur:
                t = pos_totals[cur]
                print(f"{'':>5} {'── Subtotal':<26} {'':10} {'':5} ${t['sal']:>9,} {'':>6} "
                      f"{'':>6} {'':>5} {t['season_pts']:>9.0f} ${t['rise']:>8,}")
                print()
            cur = apos

        bye_str = f"R{p['bye']}" if p['bye'] > 0 else "-"
        src = p['source'][:6]
        sgm = p['sc_season_games']
        season_pts = p['proj_avg3'] * sgm
        primary_pos = get_primary_position(p['positions'])
        threshold = keeper_thresholds.get(primary_pos, 90)
        is_keeper = p['proj_avg3'] >= threshold
        ptype = 'KEEP' if is_keeper else 'COW'
        (keepers if is_keeper else cows).append(p)
        r0 = str(int(p['r0_score'])) if p['r0_games'] > 0 else "-"

        print(f"{apos:<5} {p['name']:<26} {p['pos_str']:<10} {p['team']:<5} ${p['price']:>9,} "
              f"{p['own']:>5.1f}% {p['proj_avg3']:>6.1f} {ptype:<5} {season_pts:>9.0f} "
              f"${p['proj_rise']:>8,} {r0:>4} {src:<7} {bye_str:>5}")

        pos_totals[apos]['n'] += 1
        pos_totals[apos]['sal'] += p['price']
        pos_totals[apos]['season_pts'] += round(season_pts)
        pos_totals[apos]['rise'] += p['proj_rise']

    if cur:
        t = pos_totals[cur]
        print(f"{'':>5} {'── Subtotal':<26} {'':10} {'':5} ${t['sal']:>9,} {'':>6} "
              f"{'':>6} {'':>5} {t['season_pts']:>9.0f} ${t['rise']:>8,}")

    print(f"\n{'═'*160}")
    total_season = sum(p['proj_avg3'] * p['sc_season_games'] for p in selected)
    keeper_sal = sum(p['price'] for p in keepers)
    cow_sal = sum(p['price'] for p in cows)
    cow_rise = sum(p['proj_rise'] for p in cows)
    print(f"  TOTAL: {len(selected)} players | Salary: ${sal:,} / $10,000,000 (${10_000_000 - sal:,} remaining)")
    print(f"  Projected Season Points: {total_season:,.0f} (avg {total_season/23:.0f}/round)")
    print(f"  Structure: {len(keepers)} keepers (${keeper_sal:,}) + {len(cows)} cash cows (${cow_sal:,})")
    print(f"  Cash cow projected early rise: ${cow_rise:,}")

    high_own = [p for p in selected if p['own'] > 40]
    low_own = [p for p in selected if p['own'] < 5 and p['price'] > 200000]
    clubs = Counter(p['team'] for p in selected)
    max_club = clubs.most_common(1)[0]
    print(f"  Template: {len(high_own)} players >40% owned, {len(low_own)} PODs <5% owned (>$200k)")
    print(f"  Clubs: {len(clubs)} represented, max {max_club[1]} from {max_club[0]}")

    rucks = [p for p in selected if p['assigned_pos'] in ('RUC', 'FLX') and 'RUC' in p['positions']]
    if rucks:
        print(f"  Ruck structure:")
        for r in rucks:
            print(f"    {r['assigned_pos']}: {r['name']} (${r['price']:,}, avg {r['proj_avg3']:.0f})")
    print(f"{'═'*160}")


# =============================================================================
# 7. MONTE CARLO CONFIDENCE
# =============================================================================
def run_monte_carlo(players, n_sims=200, keeper_thresholds=None, **kwargs):
    """Run optimizer n_sims times with perturbed projections.
    Returns selection frequency for each player."""
    if keeper_thresholds is None:
        keeper_thresholds = {'DEF': 90, 'MID': 100, 'RUC': 100, 'FWD': 90}

    counts = Counter()
    pos_counts = defaultdict(Counter)  # track which position they're assigned to

    for sim in range(n_sims):
        status, team, *_ = optimise_team(
            players, keeper_thresholds=keeper_thresholds,
            proj_noise=0.15,  # ±15% std dev
            quiet=True, **kwargs
        )
        if status == 'Optimal':
            for p in team:
                counts[p['name']] += 1
                pos_counts[p['name']][p['assigned_pos']] += 1

    results = []
    for name, count in counts.most_common():
        freq = count / n_sims
        main_pos = pos_counts[name].most_common(1)[0][0]
        # Find player data
        pdata = next((p for p in players if p['name'] == name), None)
        results.append({
            'name': name, 'freq': freq, 'count': count,
            'main_pos': main_pos,
            'price': pdata['price'] if pdata else 0,
            'avg': pdata['proj_avg3'] if pdata else 0,
            'own': pdata['own'] if pdata else 0,
            'team': pdata['team'] if pdata else '',
        })
    return results


# =============================================================================
# 8. RUN SCENARIOS
# =============================================================================

# Scenario 1: MID/RUC threshold 100, DEF/FWD threshold 90
THRESH_1 = {'DEF': 90, 'MID': 100, 'RUC': 100, 'FWD': 90}
print("\n" + "█"*160)
print(f"█  SCENARIO 1: Keeper thresholds DEF/FWD≥90, MID/RUC≥100")
print("█"*160)
s, t1, o, sal, pts, rise = optimise_team(
    players, keeper_thresholds=THRESH_1,
    must_have=MUST_HAVE, must_avoid=MUST_AVOID,
    label="SCENARIO 1: DEF/FWD≥90, MID/RUC≥100"
)
if s == 'Optimal': print_team(t1, sal, pts, rise, o, THRESH_1)

# Scenario 2: MID/RUC threshold 105, DEF/FWD threshold 95
THRESH_2 = {'DEF': 95, 'MID': 105, 'RUC': 105, 'FWD': 95}
print("\n" + "█"*160)
print(f"█  SCENARIO 2: Keeper thresholds DEF/FWD≥95, MID/RUC≥105")
print("█"*160)
s, t2, o, sal, pts, rise = optimise_team(
    players, keeper_thresholds=THRESH_2,
    must_have=MUST_HAVE, must_avoid=MUST_AVOID,
    label="SCENARIO 2: DEF/FWD≥95, MID/RUC≥105"
)
if s == 'Optimal': print_team(t2, sal, pts, rise, o, THRESH_2)

# =============================================================================
# 9. MONTE CARLO (on Scenario 1 thresholds)
# =============================================================================
print("\n" + "█"*160)
print("█  MONTE CARLO: 200 simulations with ±15% projection noise")
print("█"*160)

mc_results = run_monte_carlo(
    players, n_sims=200,
    keeper_thresholds=THRESH_1,
    must_have=MUST_HAVE, must_avoid=MUST_AVOID,
)

# Show results
print(f"\n{'Name':<26} {'Pos':<5} {'Team':<5} {'Price':>9} {'Avg':>5} {'Own%':>6} {'Select%':>8}")
print("-" * 80)
for r in mc_results[:50]:
    print(f"{r['name']:<26} {r['main_pos']:<5} {r['team']:<5} ${r['price']:>8,} "
          f"{r['avg']:>5.0f} {r['own']:>5.1f}% {r['freq']:>7.1%}")

# =============================================================================
# 10. ROBUSTNESS ANALYSIS
# =============================================================================
print("\n" + "█"*160)
print("█  ROBUSTNESS: Near-misses and high-ownership omissions")
print("█"*160)

# Get Scenario 1 selected names
selected_names = {p['name'] for p in t1}

# Near misses: selected in 10-80% of MC runs but NOT in deterministic solution
print(f"\nNEAR MISSES (10-80% MC selection, not in deterministic team):")
print(f"{'Name':<26} {'Pos':<5} {'Team':<5} {'Price':>9} {'Avg':>5} {'Own%':>6} {'MC%':>7}")
print("-" * 75)
for r in mc_results:
    if r['name'] not in selected_names and 0.10 <= r['freq'] <= 0.80:
        print(f"{r['name']:<26} {r['main_pos']:<5} {r['team']:<5} ${r['price']:>8,} "
              f"{r['avg']:>5.0f} {r['own']:>5.1f}% {r['freq']:>6.1%}")

# High ownership players NOT selected
print(f"\nHIGH OWNERSHIP OMISSIONS (top 50 by own%, not in team):")
all_by_own = sorted(players, key=lambda p: -p['own'])
print(f"{'Name':<26} {'Pos':<10} {'Team':<5} {'Price':>9} {'Avg':>5} {'Own%':>6} {'MC%':>7} {'Note'}")
print("-" * 100)
shown = 0
for p in all_by_own[:50]:
    if p['name'] not in selected_names:
        mc_freq = next((r['freq'] for r in mc_results if r['name'] == p['name']), 0)
        note = ""
        if p['name'] in [n for n in MUST_AVOID]: note = "EXCLUDED (injury)"
        elif mc_freq > 0.5: note = "STRONG near-miss"
        elif mc_freq > 0.1: note = "Marginal"
        elif mc_freq > 0: note = "Rare selection"
        else: note = "Never selected"
        print(f"{p['name']:<26} {p['pos_str']:<10} {p['team']:<5} ${p['price']:>8,} "
              f"{p['proj_avg3']:>5.0f} {p['own']:>5.1f}% {mc_freq:>6.1%} {note}")
        shown += 1
        if shown >= 25: break
