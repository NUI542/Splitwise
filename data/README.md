# Data

Everything in this folder is **placeholder data**. The artwork, the people,
the shares and the wallets are invented for the demo.

| File | What it is |
|---|---|
| `registry.json` | Artworks (with each rights holder and how many editions they consented to), parties and their wallets. |
| `agreement.md` | The split agreement in plain words, as a person would sign it. |
| `sample_deal.json` | The same agreement as the deal builder's input. It passes every check. |
| `sample_deal_invalid.json` | A broken version for the demo: shares total 110% and the royalty is 12%. |
| `golden_scenarios.csv` | Nine sale scenarios. The answer columns are worked out **by hand**. |
| `sample_transfers.json` | The shape of the chain records the simulator produces for those scenarios. |

## Filling in the golden answers

The scenarios run in order (G1 to G9) under the deal in `sample_deal.json`:
10 editions at KES 15,000.00, a 10% royalty, and shares of 60% (artist-a),
15% (basix-market), 15% (broker-c) and 10% (studio-d).

Work each one out by hand, without running the code. Write every amount in
**cents** (KES 1.00 = 100) as a whole number.

- `expected_royalty_minor`: the royalty on a resale (leave empty for a first sale).
- `expected_seller_minor`: what the seller of a resale receives.
- `expected_<party>_minor`: what each co-owner receives from the sale.
- `expected_classification`: what the watch should call the transfer:
  `PRIMARY_SALE`, `SALE_ROYALTY_PAID`, `SALE_ROYALTY_MISSING` or `TRANSFER_UNVERIFIED`.
- `expected_owed_<party>_minor`: for a flagged sale, what each co-owner is still owed.

The rules to apply:

1. A price written with more than 2 decimals is rounded down to the cent.
2. First sale: each co-owner gets their share of the price, rounded down to the cent.
3. Resale: royalty = price × 10%, rounded down to the cent; the seller gets price − royalty;
   each co-owner gets their share of the royalty, rounded down to the cent.
4. Whatever is left after rounding every share down goes to the artist.
5. On a sale made elsewhere (`off-platform`), BASIX.MARKET paid nothing out. Leave the
   payout columns empty and fill in what each co-owner is owed: their share of the
   royalty minus anything they were paid.

`tests/test_golden.py` checks the code against every filled-in value. Rows or
columns left empty are reported as pending, not passed.
