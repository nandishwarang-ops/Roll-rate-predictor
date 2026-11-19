# Model bake-off (rolling origin, public data)

Origins 2024-10-01 … 2025-06-01 (9 origins x 3 horizons). Lower MAPE is better; target >= 30% below seasonal-naive.

## Overall

| model | cells | cell MAPE | vs snaive | WAPE | roll-forward MAPE | vs snaive |
|---|---|---|---|---|---|---|
| snaive | 17,440 | 29.5% | +0.0% | 3.2% | 14.5% | +0.0% |
| naive | 17,440 | 27.6% | +6.2% | 2.5% | 13.3% | +8.1% |
| ets | 17,440 | 23.2% | +21.1% | 2.4% | 12.3% | +15.5% |
| sarimax | 17,440 | 23.7% | +19.6% | 2.6% | 12.8% | +12.1% |
| gbm | 17,440 | 22.2% | +24.8% | 2.5% | 13.3% | +8.4% |
| ensemble | 17,440 | 21.9% | +25.8% | 2.3% | 12.1% | +16.6% |

## Cell MAPE by horizon (months ahead)

| model | h=1 | h=2 | h=3 |
|---|---|---|---|
| snaive | 29.3% | 29.6% | 29.4% |
| naive | 27.9% | 27.5% | 27.5% |
| ets | 23.0% | 22.9% | 23.7% |
| sarimax | 25.8% | 22.6% | 22.6% |
| gbm | 22.2% | 21.9% | 22.3% |
| ensemble | 22.4% | 21.5% | 21.7% |

## Roll-forward MAPE by starting bucket

| model | 1-30 | 31-60 | 61-90 | CURRENT |
|---|---|---|---|---|
| snaive | 14.9% | 11.5% | 10.8% | 20.1% |
| naive | 13.8% | 11.1% | 11.4% | 16.6% |
| ets | 12.9% | 9.5% | 9.3% | 16.8% |
| sarimax | 13.1% | 9.9% | 9.5% | 17.9% |
| gbm | 13.3% | 9.4% | 9.1% | 20.6% |
| ensemble | 12.5% | 9.3% | 8.9% | 17.2% |

**Selected: `ensemble`** (cell MAPE 21.9%, 26% better than seasonal-naive).