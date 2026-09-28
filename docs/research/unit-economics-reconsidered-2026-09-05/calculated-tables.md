## OBSERVED

| Service | Previous period usage | Current partial period usage |
| --- | --- | --- |
| Postgres | $1.68 | $0.42 |
| api-service | $1.38 | $0.24 |
| Redis | $0.13 | $0.02 |
| partner-mcp-pilot | $0.43 | $0.08 |
| deleted service | $0.06 | $0.00 |
| Project total | $3.68 | $0.76 |

## SCENARIOS

| Scenario | Fee / month | Actions / month | Delivery hours | Delivery cost | Contribution | Margin |
| --- | --- | --- | --- | --- | --- | --- |
| Bounded, low-touch | $499.00 | 10,000 | 1.012 | $125.70 | $373.30 | 74.8% |
| Working illustration | $999.00 | 100,000 | 3.125 | $343.64 | $655.36 | 65.6% |
| Same workload, higher price | $1,500.00 | 100,000 | 3.125 | $363.18 | $1,136.83 | 75.8% |
| Support-heavy | $999.00 | 100,000 | 13.000 | $1,084.26 | -$85.26 | -8.5% |
| Volume stress, unbenchmarked | $999.00 | 1,000,000 | 6.250 | $778.01 | $220.99 | 22.1% |

## WATERFALL

| Working illustration, 100K attempts | USD per customer-month |
| --- | --- |
| Revenue | $999.00 |
| Resource allowance | $50.00 |
| Other delivery allowance | $20.00 |
| Routine support: 3h x $75 | $225.00 |
| Exceptions: 0.125h x $75 | $9.38 |
| Collection fees | $29.27 |
| Planning reserve | $9.99 |
| Delivery cost | $343.64 |
| Contribution | $655.36 |

## PRICE_HOURS

| Monthly price | 1 routine hour | 3 routine hours | 8 routine hours | 70% margin: max routine hours |
| --- | --- | --- | --- | --- |
| $249.00 | 34.0% | -26.3% | -176.9% | -0.20h |
| $499.00 | 65.1% | 35.0% | -40.1% | 0.67h |
| $999.00 | 80.6% | 65.6% | 28.1% | 2.41h |
| $1,500.00 | 85.8% | 75.8% | 50.8% | 4.16h |
| $2,500.00 | 89.9% | 83.9% | 68.9% | 7.64h |

## RESOURCE

| Resource allowance / month | Contribution at $999 | Margin | Revenue for 70% margin |
| --- | --- | --- | --- |
| $5.00 | $700.36 | 70.1% | $994.92 |
| $20.00 | $685.36 | 68.6% | $1,052.39 |
| $50.00 | $655.36 | 65.6% | $1,167.34 |
| $150.00 | $555.36 | 55.6% | $1,550.48 |
| $500.00 | $205.36 | 20.6% | $2,891.48 |
| $1,000.00 | -$294.64 | -29.5% | $4,807.18 |

## COMMITMENT

| Illustrative workspace commitment | Customers | Usage total ($20 each) | Workspace bill | Unabsorbed minimum | Allocated / customer | Next resource increment |
| --- | --- | --- | --- | --- | --- | --- |
| $20.00 | 1 | $20.00 | $20.00 | $0.00 | $20.00 | $20.00 |
| $20.00 | 5 | $100.00 | $100.00 | $0.00 | $20.00 | $20.00 |
| $20.00 | 20 | $400.00 | $400.00 | $0.00 | $20.00 | $20.00 |
| $20.00 | 50 | $1,000.00 | $1,000.00 | $0.00 | $20.00 | $20.00 |
| $1,000.00 | 1 | $20.00 | $1,000.00 | $980.00 | $1,000.00 | $0.00 |
| $1,000.00 | 5 | $100.00 | $1,000.00 | $900.00 | $200.00 | $0.00 |
| $1,000.00 | 20 | $400.00 | $1,000.00 | $600.00 | $50.00 | $0.00 |
| $1,000.00 | 50 | $1,000.00 | $1,000.00 | $0.00 | $20.00 | $20.00 |

## ONBOARD

| Setup fee | 10 delivery hours | 20 delivery hours | 40 delivery hours |
| --- | --- | --- | --- |
| $1,000.00 | $110.70 | -$639.30 | -$2,139.30 |
| $2,500.00 | $1,552.20 | $802.20 | -$697.80 |
| $5,000.00 | $3,954.70 | $3,204.70 | $1,704.70 |

## CAC

| Acquisition effort per win | Acquisition cost | Payback at working illustration | 12-month contribution after acquisition |
| --- | --- | --- | --- |
| 10h + $300 expenses | $1,050.00 | 1.6 months | $6,814.37 |
| 40h + $300 expenses | $3,300.00 | 5.0 months | $4,564.37 |
| 100h + $300 expenses | $7,800.00 | 11.9 months | $64.37 |

## COMPANY

| Shared monthly overhead | Customers to cover overhead | Monthly direct delivery hours |
| --- | --- | --- |
| $3,000.00 | 5 | 15.6h |
| $10,000.00 | 16 | 50.0h |
| $30,000.00 | 46 | 143.8h |

## ROI

| Monthly platform fee | Buyer hours to break even ($100/h) | Hours for 3x gross benefit | $500 net incidents avoided to break even |
| --- | --- | --- | --- |
| $499.00 | 4.99h | 14.97h | 0.998 |
| $999.00 | 9.99h | 29.97h | 1.998 |
| $1,500.00 | 15.00h | 45.00h | 3.000 |
| $2,500.00 | 25.00h | 75.00h | 5.000 |

## RETENTION

| Net logical bytes / action | 100K/month, month 12 with 3x footprint | 1M/month, month 12 |
| --- | --- | --- |
| 4 KB | 14.4 GB | 144.0 GB |
| 12 KB | 43.2 GB | 432.0 GB |
| 100 KB | 360.0 GB | 3600.0 GB |
