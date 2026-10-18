# Edition Deal Agent

A module for the BASIX.MARKET NFT marketplace that runs the **deal** behind
a limited run of digital editions of a physical artwork. An agent built
on MeTTa rules (OpenCog Hyperon) holds each deal as rules and does three
jobs:

1. **Check** the deal before it goes live, then **lock** it.
2. **Pay out** every sale by the deal, with an explanation you can trace.
3. **Watch** resales and flag any where the royalty wasn't paid.

A web app shows all three, with the agent's reasoning on screen. Minting
and money movement are simulated; the reasoning is the product.

> **Placeholder data.** The artwork, people, shares and wallets in this repo
> are invented for the demo. They aren't real people, real consent, or an
> agreement with BASIX.MARKET or any partner.

## Hackathon entry

| | |
|---|---|
| Event | State of the Art Hackathon 2026 (BASIX.MARKET) |
| Track | **Track 02: MeTTa Omega (Builders)** |
| Challenge | **6. BASIX.MARKET: Mature Build**: a working module for the BASIX NFT Marketplace |
| Partner brief | AI for Peace: phigital editions with royalties to the artists. Partner briefs are proposals until the partner confirms them. This build uses no AI for Peace works or data. |
| Team | _To be filled in: names and BASIX.MARKET profiles_ |
| Demo video | _Link to be added_ |
| AI use | See [AI_DISCLOSURE.md](AI_DISCLOSURE.md) |

## What it does

**1. Check and lock the deal.** A deal is an artwork, a currency, an
edition count, a price, the co-owners with their shares and payout
wallets, and a resale royalty rate. The agent turns it into MeTTa facts
and checks it against 50+ rules as you type. Some rules are contradictions
within the deal (shares not adding up to 100%, two artists, a price too
small to split). Others check against outside records: the artwork's
rights holder, the editions they consented to, another deal already
locked on the same artwork. Every finding names its rule. When the deal
is valid, each co-owner approves that exact version in the app, and the
agent checks the approvals before it locks.

**2. Pay out by the deal.** Each sale on BASIX.MARKET goes through the
agent. A primary sale is split by share; a resale pays a royalty, split
the same way, and the seller keeps the rest. Every share is rounded down
to the cent and the leftover goes to the artist, so the lines always add
up to the price. The result comes with a structured trace (rule, inputs,
result). "Why did I get this?" is answered from that trace, so the
numbers explained are the numbers paid.

**3. Watch that the deal is honoured.** The agent reads every transfer
and payment on the (simulated) chain and classifies each transfer:

| Class | Meaning |
|---|---|
| `PRIMARY_SALE` | A mint that matches a recorded primary sale |
| `SALE_ROYALTY_PAID` | A paid sale where every co-owner got their royalty share |
| `SALE_ROYALTY_MISSING` | A paid sale where some co-owners didn't; it states who is owed what |
| `TRANSFER_UNVERIFIED` | No payment in the transaction (a gift, a wallet move, or a sale settled elsewhere). Nobody is accused. |

Anything that isn't paid or a primary sale becomes a flag, with its
evidence. A person resolves or dismisses it, with a reason that's kept.

## How it works

```
React app (4 screens) ──HTTP──► FastAPI (api/) ──► service layer (agent/)
                                                    ├─ MeTTa rules (rules/*.metta) on hyperon
                                                    │    checks · payout split · classification → traces
                                                    ├─ SQLite: versions, approvals, locks,
                                                    │    append-only ledger, flags
                                                    └─ ChainAdapter ◄── simulator (later: a real chain)
OmegaClaw (chat) ──read-only skills──► FastAPI
```

| Layer | Holds | Doesn't hold |
|---|---|---|
| `rules/` (MeTTa) | Every check, the payout split, the classification, the rule catalogue | Storage, HTTP |
| `agent/` (Python) | Turning input into facts, storage, the chain adapter, an independent sum check, text templates filled from traces | Business rules |
| `web/` (React) | Screens | Business rules or money arithmetic: amounts arrive formatted |

A rule looks like this (from `rules/validation.metta`):

```metta
(= (draft-rule $v)
   (let $xs (bps-values $v)
     (if (== $xs ())
         (empty)
         (let $total (sum-of $xs)
           (if (== $total 10000)
               (empty)
               (violation error shares-not-100 shares ((total-bps $total))))))))
```

Each request gets a fresh MeTTa runner with the rules and that request's
facts only. The facts are shown in the app ("the facts the agent reasoned
over"), so every decision can be traced back to its inputs.

## Decisions

From the build brief (final):

1. **No separate resale fee.** BASIX.MARKET earns only through its co-owner share of the royalty.
2. **Chain:** simulated, behind a `ChainAdapter` (`read_transfers`, `read_payments`). A real chain plugs in without changing the agent.
3. **Consent:** in-app approval, recorded with the co-owner's name, the deal version and the time.
4. **Resale royalty** is split among co-owners in the same proportions as the primary split.
5. **Royalty rate:** any rate from 0% to below 100%; above 10% is a warning, not an error.
6. **Rounding:** whole minor units; each share rounded down; any leftover goes to the artist.
7. **Stack:** MeTTa on Hyperon, Python + FastAPI, React (Vite + TypeScript), SQLite.

Agreed while planning:

- **Currency:** KES, counted in cents. An amount written with more than 2 decimals is rounded down to the cent. Currency stays a deal setting; adding one is a line in `agent/money.py`.
- **Shares and the royalty rate** are whole basis points (10000 = 100%). No floats anywhere.
- **Royalty rounding:** the royalty is rounded down to the cent and the seller receives price − royalty. The fraction of a cent dropped can't be paid to anyone, so it stays with the seller. The royalty is then split by share, with the leftover cents to the artist.
- **When checks run:** draft checks run live while editing. Lock checks add consent, versions and time. Sale checks run on every sale event.
- **Errors and warnings:** every contradiction is an error, except a royalty above 10% and a royalty so small that every co-owner except the artist would get 0 at the deal's own price (skipped at 0%). Those two are warnings.
- **Versions:** a locked version never changes; any edit makes a new version that every co-owner approves again. Each sale uses the version in force when it happened and records it. Sales already paid are never recalculated. Locked terms are hashed, and a sale is refused if the stored terms no longer match the lock.
- **Exactly once:** an event ID is processed once. Replaying the same event returns the original payout; reusing the ID for a different sale is refused.
- **Where events come from:** sales on BASIX.MARKET go through the agent and are then settled on the simulated chain. A resale elsewhere, or a gift, is written only to the chain, and the watch finds it.
- **Partial royalty** counts as `SALE_ROYALTY_MISSING`, with only the shortfall owed.
- **Price ceiling:** KES 10 billion. MeTTa's integers are 64-bit and wrap silently, so the ceiling keeps every calculation exact.
- **OmegaClaw is read-only:** it can explain, list and run the watch, never approve, lock or sell (see [omega/README.md](omega/README.md)).

## Setup

You need Python 3.8 to 3.12 (hyperon 0.2.10 has no wheels for 3.13; we
use 3.11) and Node 18 or later.

Windows (PowerShell):

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd web; npm install; npm run build; cd ..
.venv\Scripts\python -m uvicorn api.main:create_app --factory --port 8000
```

macOS / Linux:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
(cd web && npm install && npm run build)
.venv/bin/python -m uvicorn api.main:create_app --factory --port 8000
```

Open <http://127.0.0.1:8000>. The API's own docs are at `/docs`.

To work on the UI with hot reload, keep the API running and start
`npm run dev` in `web/`, then open <http://localhost:5173>.

Settings (optional; copy `.env.example` to `.env` or set them in the shell):

| Variable | Default | Used by |
|---|---|---|
| `EDA_DB_PATH` | `var/edition_deals.db` | the API |
| `VITE_API_BASE` | `http://127.0.0.1:8000` | the Vite dev server's proxy |
| `EDA_API_BASE` | `http://host.docker.internal:8000` | the OmegaClaw skills |

## The demo run

This is the 3-minute video, entirely in the app:

1. **Deal → Load broken sample.** The agent flags *"The shares add up to 110.00%, not 100.00%"* (`shares-not-100`) and warns about the 12% royalty (`royalty-above-10`).
2. **Fix** the artist's share to 60. The check turns valid (one warning) and the plain-language summary appears. **Save deal for approval.**
3. **Approve** as three of the four co-owners, then **Lock**. The agent refuses: *"Print Studio D hasn't approved version 1"* (`approval-missing`).
4. Approve as the last co-owner and **Lock**. Version 1 is active.
5. **Sales → Primary sale**, then **Resale with royalty**: both are paid out and appear in the ledger.
6. **Resale without royalty**, then **Gift transfer**: these happen off BASIX.MARKET, so they appear on the chain but not in the ledger.
7. **Watch → Scan the chain.** Four transfers, four classes. The unpaid resale is flagged with what each co-owner is owed; the gift is flagged as unverified, with no royalty claimed.
8. **Sales → click a payout line** on the resale. **Explain** answers *"Why did Print Studio D get KES … for sale …?"* step by step, with the trace beside it.
9. **What's next:** a real chain adapter, signed approvals, and OmegaClaw in chat.

Footer controls: **Seed a locked sample deal** skips steps 1–4; **Reset everything** wipes the demo.

## Tests

```bash
.venv/Scripts/python -m pytest      # Windows
.venv/bin/python -m pytest          # macOS / Linux
```

The suite takes about 2.5 minutes, because each MeTTa query takes
0.3–2 seconds. It covers:

- every contradiction rule (`tests/test_validation.py`)
- consent, versions, locking, timing and exactly-once sales (`tests/test_lifecycle.py`)
- payout, rounding and explanations (`tests/test_payout.py`)
- the watch and flags (`tests/test_watch.py`)
- Hypothesis property tests: exact sums, leftover to the artist, no double payment on replay, locked deals unchanged (`tests/test_properties.py`)
- the whole demo run over HTTP (`tests/test_api.py`)

**Golden scenarios.** `data/golden_scenarios.csv` has nine scenarios
whose answers are worked out **by hand** (see [data/README.md](data/README.md)).
`tests/test_golden.py` compares the code with every filled-in answer to
the cent. Until the answers are in, those rows are reported as skipped
(pending), not passed.

## API

| Method | Path | |
|---|---|---|
| POST | `/deals/check` | Check a draft (stores nothing) → `{valid, errors, warnings, summary, facts}` |
| POST | `/deals` | Save a checked draft as the next version |
| GET | `/deals` · `/deals/{id}/versions` | Deals; versions with approvals and status |
| POST | `/deals/{id}/approve` | `{version, party_id}` |
| POST | `/deals/{id}/lock` | `{version}` → `{deal_id, version, locked_at}`, or 422 with the agent's reasons |
| POST | `/sales` | Record a sale → `{sale_id, deal_version, lines, trace}` |
| GET | `/sales` · `/sales/{id}/explain?party=` | The ledger; `{trace, explanation}` |
| POST | `/watch/scan` | Classify every transfer; raise flags |
| GET / PATCH | `/flags` · `/flags/{id}` | List flags; resolve, dismiss or reopen with a reason |
| POST | `/sim/{scenario}` | `primary-sale`, `resale-with-royalty`, `resale-without-royalty`, `resale-partial-royalty`, `gift-transfer`, `seed-locked-deal`, `reset` |
| GET | `/rules` · `/registry` · `/samples` · `/chain/transfers` | The rule catalogue, placeholder registry, sample deals, raw chain records |

Errors are JSON: `{error: "<code>", message, report?}`, where `report` lists the rules that refused the request.

## Repository layout

```
rules/    MeTTa: deal facts schema and rule catalogue, checks, payout, classification
agent/    Python service layer, chain adapter and simulator, storage, explanations
api/      FastAPI app
web/      React app (Deal, Sales, Explain, Watch)
omega/    OmegaClaw skills (read-only)
data/     placeholder registry, agreement, sample deals, golden scenarios
tests/    pytest + Hypothesis
```

The hackathon starter files (`BRIEF.md`, `SUBMISSION.md`, `tracks/`,
`AGENTS.md`, `CLAUDE.md`) are kept as they came from the template.

## Limits and what's next

- **The chain is simulated.** Next: a Cardano or EVM adapter implementing `read_transfers` and `read_payments`.
- **Approvals are clicks, not signatures.** Anyone using the app can approve as anyone. Next: each co-owner signs in, or signs with their wallet.
- **Speed.** The hyperon interpreter takes about a second for a full deal check. That's fine for the demo; at scale the rules would need caching or a faster runtime.
- **OmegaClaw** skills are written and tested against the API, but not yet run inside OmegaClaw.
- **One currency** is configured (KES). Others are a one-line addition, within the 64-bit limit.
- **A royalty paid later**, in a separate transaction, isn't matched automatically; a person resolves the flag with a reason.

## Licence

No licence has been chosen yet.
