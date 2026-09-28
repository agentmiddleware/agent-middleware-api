## SCENARIOS

| Monthly scenario | Lean pilot | Base account | Volume account | Troubled account |
| --- | --- | --- | --- | --- |
| Unique governed attempts | 100,000 | 1,000,000 | 10,000,000 | 1,000,000 |
| Revenue (hypothesis) | $1,500.00 | $2,400.00 | $11,400.00 | $2,400.00 |
| Baseline infrastructure | $75.00 | $150.00 | $500.00 | $450.00 |
| Incremental machine cost | $3.00 | $100.00 | $2,000.00 | $500.00 |
| Routine delivery/support labor | $75.00 | $225.00 | $600.00 | $1,200.00 |
| Exception-handling labor | $1.88 | $93.75 | $937.50 | $5,000.00 |
| Payment fees | $43.80 | $69.90 | $330.90 | $69.90 |
| Service concession/loss allowance | $15.00 | $24.00 | $114.00 | $24.00 |
| Enterprise allocation: EXCLUDED | $0.00 | $0.00 | $0.00 | $0.00 |
| Delivery cost incl. labor | $213.68 | $662.65 | $4,482.40 | $7,243.90 |
| Monthly delivery contribution | $1,286.33 | $1,737.35 | $6,917.60 | -$4,843.90 |
| Contribution margin | 85.8% | 72.4% | 60.7% | -201.8% |
| Revenue per 1,000 attempts | $15.00 | $2.40 | $1.14 | $2.40 |
| Delivery cost per 1,000 attempts | $2.14 | $0.66 | $0.45 | $7.24 |

## ENTERPRISE

| Incremental Enterprise allocation / customer-month | Contribution at $2,400 revenue | Margin | Revenue needed for 70% margin |
| --- | --- | --- | --- |
| $0 | $1,737.35 | 72.4% | $2,180.27 |
| $200 | $1,537.35 | 64.1% | $2,946.55 |
| $500 | $1,237.35 | 51.6% | $4,095.98 |
| $1,000 | $737.35 | 30.7% | $6,011.69 |
| $2,000 | -$262.65 | -10.9% | $9,843.10 |
| $5,000 | -$3,262.65 | -135.9% | $21,337.36 |

## VOLUME

| Monthly attempts | Default-equivalent $0.0001/action | Hybrid revenue | Delivery cost | Hybrid margin |
| --- | --- | --- | --- | --- |
| 10,000 | $1.00 | $1,500.00 | $435.74 | 71.0% |
| 100,000 | $10.00 | $1,500.00 | $453.18 | 69.8% |
| 1,000,000 | $100.00 | $2,400.00 | $662.65 | 72.4% |
| 10,000,000 | $1,000.00 | $11,400.00 | $2,757.40 | 75.8% |

## SUPPORT

| Routine support hours / month | At $75 / hour | Contribution | Margin |
| --- | --- | --- | --- |
| 1 | $75.00 | $1,887.35 | 78.6% |
| 3 | $225.00 | $1,737.35 | 72.4% |
| 5 | $375.00 | $1,587.35 | 66.1% |
| 10 | $750.00 | $1,212.35 | 50.5% |
| 20 | $1,500.00 | $462.35 | 19.3% |

## EXCEPTIONS

| Exception rate | Exceptions per million | Human hours (10% escalated, 15 min each) | Labor cost | Margin |
| --- | --- | --- | --- | --- |
| 0.001% | 10 | 0.25 | $18.75 | 75.5% |
| 0.005% | 50 | 1.25 | $93.75 | 72.4% |
| 0.010% | 100 | 2.50 | $187.50 | 68.5% |
| 0.100% | 1,000 | 25.00 | $1,875.00 | -1.8% |
| 1.000% | 10,000 | 250.00 | $18,750.00 | -705.0% |

## RETENTION

| Logical bytes per new action | 12-month data at 1M/month, 3x footprint (GB) | Monthly volume cost at month 12 | At 10M/month |
| --- | --- | --- | --- |
| 4 KB | 144 | $21.60 | $216.00 |
| 12 KB | 432 | $64.80 | $648.00 |
| 100 KB | 3,600 | $540.00 | $5,400.00 |
| 1,000 KB | 36,000 | $5,400.00 | $54,000.00 |

## CPU

| Aggregate CPU seconds / new action | CPU dollars / million | CPU dollars / 1,000 |
| --- | --- | --- |
| 5 ms | $0.04 | $0.000039 |
| 20 ms | $0.15 | $0.000154 |
| 100 ms | $0.77 | $0.000772 |
| 500 ms | $3.86 | $0.003860 |

## BREAK_EVEN

| Incremental Enterprise allocation / customer | Customers for $3K overhead | For $10K | For $30K |
| --- | --- | --- | --- |
| $0 | 2 | 6 | 18 |
| $500 | 3 | 9 | 25 |
| $1,000 | 5 | 14 | 41 |
| $2,000 | No finite break-even | No finite break-even | No finite break-even |

## CAC

| Acquisition cost / customer | Payback with E=$0 | Payback with E=$1,000 |
| --- | --- | --- |
| $2,000 | 1.15 months | 2.71 months |
| $8,000 | 4.60 months | 10.85 months |
| $20,000 | 11.51 months | 27.12 months |

## LTV

| Monthly logo churn assumption | 12-month logo survival | 36-month capped contribution value | Value / $8K CAC |
| --- | --- | --- | --- |
| 1% | 88.6% | $52,743.65 | 6.59x |
| 3% | 69.4% | $38,567.57 | 4.82x |
| 5% | 54.0% | $29,264.65 | 3.66x |
| 10% | 28.2% | $16,982.10 | 2.12x |

## PAYMENTS

| Single customer payment | Domestic card fee | Effective card rate | ACH processing illustration |
| --- | --- | --- | --- |
| $5 | $0.45 | 8.90% | $0.04 |
| $20 | $0.88 | 4.40% | $0.16 |
| $100 | $3.20 | 3.20% | $0.80 |
| $500 | $14.80 | 2.96% | $4.00 |
| $2,400 | $69.90 | 2.91% | $5.00 |
