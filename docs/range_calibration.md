# Range calibration (leave-one-origin-out)

Sigma/kappa/phi are re-fitted without the origin being scored. lambda per horizon chosen on the grid so the 80% range covers ~80%.

persistence phi = 0.9 (fitted cell-level value was 0.90); lambda by horizon: [1.7, 2.2, 2.5]

Uncalibrated coverage (%):

| metric        |   1 |   2 |   3 |
|:--------------|----:|----:|----:|
| npa_accounts  |  44 |  37 |  26 |
| npa_additions |  67 |  63 |  52 |

Calibrated coverage (%):

| metric        |   1 |   2 |   3 |
|:--------------|----:|----:|----:|
| npa_accounts  |  78 |  78 |  89 |
| npa_additions |  89 |  89 |  81 |

Mean 80% range width as % of the actual value:

| metric        |    1 |    2 |    3 |
|:--------------|-----:|-----:|-----:|
| npa_accounts  |  4.3 |  8.4 | 13.5 |
| npa_additions | 17.9 | 23.4 | 33.1 |
