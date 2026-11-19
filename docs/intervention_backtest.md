# Intervention forecast backtest (Lender A WEST 31-60 agency attrition)

Origins Apr/May/Jun 2025, horizon 1-3, 9 forecast points. Pool months hold ~600 accounts, so each actual carries ~2pp sampling noise: treat differences below ~1pp as inconclusive.

| origin   |   h | month   |   actual |   unadjusted |   counterfactual |   blip |   adjusted |   lasting |
|:---------|----:|:--------|---------:|-------------:|-----------------:|-------:|-----------:|----------:|
| 2025-04  |   1 | 2025-05 |    58.77 |        55.1  |            53.57 |  53.57 |      57.08 |     58.58 |
| 2025-04  |   2 | 2025-06 |    55.7  |        55.45 |            53.69 |  53.69 |      57.2  |     58.7  |
| 2025-04  |   3 | 2025-07 |    60.65 |        54.91 |            53.53 |  53.53 |      57.04 |     58.54 |
| 2025-05  |   1 | 2025-06 |    55.7  |        56.31 |            54.25 |  54.25 |      56.99 |     58.16 |
| 2025-05  |   2 | 2025-07 |    60.65 |        55.93 |            54.27 |  54.27 |      57.02 |     58.19 |
| 2025-05  |   3 | 2025-08 |    56.29 |        56.77 |            54.95 |  54.95 |      57.69 |     58.87 |
| 2025-06  |   1 | 2025-07 |    60.65 |        55.46 |            53.52 |  53.52 |      56.49 |     57.76 |
| 2025-06  |   2 | 2025-08 |    56.29 |        56.17 |            54.24 |  54.24 |      57.21 |     58.48 |
| 2025-06  |   3 | 2025-09 |    55.66 |        56.94 |            54.62 |  54.62 |      57.59 |     58.86 |

MAE (pp): {'unadjusted': 2.45, 'counterfactual': 3.74, 'blip': 3.74, 'adjusted': 2.24, 'lasting': 2.34}

Bias (pp): {'unadjusted': -1.92, 'counterfactual': -3.74, 'blip': -3.74, 'adjusted': -0.67, 'lasting': 0.64}

MAE by horizon (unadjusted vs adjusted): {1: {'unadjusted': 3.16, 'adjusted': 2.38}, 2: {'unadjusted': 1.7, 'adjusted': 2.01}, 3: {'unadjusted': 2.49, 'adjusted': 2.31}}