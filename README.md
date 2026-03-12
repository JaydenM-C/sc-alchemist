# AFL SuperCoach 2026 Optimizer
## Complete System Documentation

### Quick Start
```bash
pip install pulp openpyxl
python sc2026_optimiser_v4.py
```

### Required Input Files
All must be in the same directory as the script, or adjust paths in the script.

1. **AFL_supercoach_playerlist_2026_R0** — Raw player JSON from SC website (place in same dir or update path)
2. **rookie_projections.csv** — Custom rookie average projections (37 players)
3. **midprice_projections.csv** — Custom mid-price breakout projections (31 players)
4. **excluded_players.csv** — Injury exclusions (92 players)
5. **r1_team_exclusions.txt** — Players not named in R1 teams (CAR/RIC so far, add more as teams drop)

### What the Optimizer Does

**Dual-objective integer program** that separately values two player types:

- **KEEPERS** (avg ≥ position threshold): Valued on `proj_avg × sc_season_games`
  - Season-long output is all that matters — you're never selling them
  - Position-specific thresholds: DEF/FWD ≥ 90 (or 95), MID/RUC ≥ 100 (or 105)

- **CASH COWS** (avg < threshold): Valued on `proj_avg × 8 + 3.5 × (proj_rise / 1000)`
  - Held for ~8 rounds then upgraded
  - Price rise is heavily weighted — that's their purpose

**Blended projections** combine:
- 2025 season average (weighted by games played, capped at 80%)
- SC Plus per-game projection (average of non-zero ppts rounds, NOT pavg3 which includes bye zeros)
- Custom overrides take highest precedence

**Early bye handling:**
- Opening Round clubs (SYD, CAR, GCS, GEE, GWS, HAW, BRL, WBD, STK, COL) play 22 SC games vs 23 for others
- Keepers get 22.5 (0.5 = bench cover approximation) vs 23.0

### Custom Override Hierarchy (highest precedence first)
1. User spreadsheet overrides (Butters 120, Gulden 108, Petracca 108, etc.)
2. Ruck rule-change overrides (Xerri 128, Grundy 122, English 114, etc.)
3. Midprice breakout projections (midprice_projections.csv)
4. Rookie projections (rookie_projections.csv)
5. Blended default (season avg × weight + SC Plus per-game × remainder)

### Hard Constraints
- **MUST HAVE:** Tristan Xerri, Brodie Grundy, Lachlan McAndrew, Liam Reidy
- **MUST AVOID:** All injured/excluded players + R1 team omissions + Adam Treloar, Reilly O'Brien

### Monte Carlo
200 simulations with ±15% Gaussian noise on all projections.
Selection frequency = confidence that a player belongs in the optimal team.

### Key Model Parameters
| Parameter | Value | Rationale |
|-----------|-------|-----------|
| GAMES_WEIGHT_CAP | 0.80 | Max 80% weight on season avg, min 20% SC Plus |
| PRICE_CHANGE_PER_PT | 440 | ~$440 price rise per point above BE per round |
| cow_rounds | 8 | Cash cows held ~8 rounds before upgrade |
| w_cow_rise | 3.5 | $1000 of price rise = 3.5 objective points for cows |
| proj_noise (MC) | 0.15 | ±15% std dev for Monte Carlo perturbation |

### To Re-run with Updated R1 Teams
1. Add new team exclusions to `r1_team_exclusions.txt` (one name per line)
2. Update any projection overrides in the script's `custom_overrides.update({...})` block
3. If you have a new JSON data file, update the path at the top of the script
4. Run: `python sc2026_optimiser_v4.py`

### Version History
- v1: Basic 3-round optimizer with SC Plus projections
- v2: Blended projections (season avg + SC Plus), injury exclusions, custom overrides
- v3: Season-long objective function, bye-adjusted scoring
- v4: **Current.** Dual keeper/cow objective, position-specific thresholds, Monte Carlo, per-game SC Plus fix, R0 data integration
