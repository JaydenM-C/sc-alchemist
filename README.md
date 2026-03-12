# AFL SuperCoach 2026 Optimizer

## Quick Start

```bash
pip install pulp openpyxl

# Step 1: Generate the projections spreadsheet
python prepare_projections.py

# Step 2: Open SC2026_AllPlayers_Projections.xlsx in Excel/Sheets
#   - Review "Our Proj" column (auto-generated blended projections)
#   - Add overrides in "User Proj" column (green) where you disagree
#   - Mark players in "User Incl/Excl" column:
#       1 = MUST HAVE (force into team)
#       0 = MUST AVOID (exclude completely)
#       blank = let the optimiser decide
#   - Save the file

# Step 3: Run the optimiser
python run_optimiser.py
```

## File Structure

### Scripts
- **prepare_projections.py** — Generates the master spreadsheet from raw data
- **run_optimiser.py** — Reads the spreadsheet, runs dual-objective optimizer + Monte Carlo

### Input Data
- **AFL_supercoach_playerlist_2026_R0** — Raw player JSON scraped from SC website
- **rookie_projections.csv** — Custom rookie projections (from preseason analysis)
- **midprice_projections.csv** — Custom mid-price breakout projections

### Generated Files
- **SC2026_AllPlayers_Projections.xlsx** — Master spreadsheet (output of Step 1, input to Step 2)
- **excluded_players.csv** — Auto-extracted injury list from JSON

## How the Projections Work

### Blending Formula
For each player without a custom override:
```
games_weight = min(prev_games / 22, 1.0) x 0.80
projection = games_weight x prev_season_avg + (1 - games_weight) x sc_plus_per_game
```
Where sc_plus_per_game is the average of non-zero projected round scores (excluding bye-round zeros).

### Override Precedence (highest first)
1. **User Proj** (from spreadsheet — your manual last-minute overrides)
2. **Hardcoded overrides** (ruck analysis, post-R0 review — baked into Our Proj)
3. **midprice_projections.csv** (breakout analysis)
4. **rookie_projections.csv** (rookie analysis)
5. **Blended default** (automatic)

## How the Optimizer Works

### Dual Objective: Keepers vs Cash Cows
Players are classified by position-specific thresholds:

| Position | Scenario 1 | Scenario 2 |
|----------|-----------|-----------|
| DEF/FWD  | >= 90     | >= 95     |
| MID/RUC  | >= 100    | >= 105    |

**Keepers** (avg >= threshold): value = proj_avg x sc_season_games
**Cash Cows** (avg < threshold): value = proj_avg x 8 + 3.5 x (proj_rise / 1000)

### Early Bye Handling
Opening Round clubs play 22 SC-counting games (vs 23 for others).
Keepers from these clubs get 22.5 games (0.5 = bench cover approximation).

### Monte Carlo Confidence
200 simulations with +/-15% Gaussian noise on projections.
Selection frequency = confidence that a player belongs in the optimal team.

## Typical Workflow for Team Announcements

1. Run prepare_projections.py to get fresh spreadsheet
2. As team lists drop, mark omitted players with 0 in User Incl/Excl
3. Mark your locked-in players with 1 in User Incl/Excl
4. Override any projections in User Proj based on team news
5. Save and run run_optimiser.py
6. Review Monte Carlo confidence and near-misses
7. Repeat as more teams are announced
