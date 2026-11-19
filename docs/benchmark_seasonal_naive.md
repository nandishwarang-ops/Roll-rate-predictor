# Seasonal-naive benchmark (public data)

Forecast for month m = same segment/bucket rate in m-12 (seasonal) or m-1 (naive). Scored on the last N public months; MAPE excludes zero-rate cells and cells with <30 opening accounts.

| level | method | last N months | cells scored | MAPE | WAPE |
|---|---|---|---|---|---|
| segment | seasonal | 12 | 7,759 | 29.0% | 3.1% |
| segment | seasonal | 3 | 1,926 | 30.0% | 2.9% |
| segment | naive | 12 | 7,759 | 27.3% | 2.4% |
| segment | naive | 3 | 1,926 | 25.9% | 1.9% |
| lender_product | seasonal | 12 | 2,051 | 16.8% | 2.4% |
| lender_product | seasonal | 3 | 513 | 17.9% | 2.2% |
| lender_product | naive | 12 | 2,051 | 16.3% | 1.6% |
| lender_product | naive | 3 | 513 | 15.3% | 0.9% |
| lender_region | seasonal | 12 | 2,735 | 19.6% | 2.4% |
| lender_region | seasonal | 3 | 684 | 19.3% | 2.2% |
| lender_region | naive | 12 | 2,735 | 18.4% | 1.8% |
| lender_region | naive | 3 | 684 | 17.7% | 1.2% |
| lender | seasonal | 12 | 684 | 10.2% | 2.0% |
| lender | seasonal | 3 | 171 | 11.2% | 1.8% |
| lender | naive | 12 | 684 | 9.3% | 1.3% |
| lender | naive | 3 | 171 | 6.8% | 0.5% |