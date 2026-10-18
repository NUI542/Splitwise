# OmegaClaw skills

These files let an [OmegaClaw](https://innovationlab.fetch.ai/resources/docs/examples/openclaw/omegaclaw-agentverse-skills)
agent talk about edition deals in chat: what's in force, who was paid
what and why, and which resales skipped the royalty.

| Skill | What it does |
|---|---|
| `(deal-status)` | Every deal, its newest version and the version in force. |
| `(recent-sales)` | The latest sales in the ledger and who was paid what. |
| `(explain-payout "sale-id" "party-id")` | The agent's own answer to "why did they get this?" |
| `(scan-royalties)` | Runs the watch and reports what needs a look. |
| `(open-flags)` | Open flags, each with its evidence. |
| `(check-deal "{...json...}")` | Checks a draft deal against every rule without saving it. |

## Why the chat agent can only read and watch

The deal agent's decisions come from the MeTTa rules in `/rules`, never
from a language model. OmegaClaw sits in front as a conversational layer:
it can ask questions and run the watch, but no skill approves, locks,
records a sale or resets anything. OmegaClaw can rewrite its own skills
and run shell commands, so keep these as its only route to the deal agent
and leave its security policy on. That's how a business could let people
chat with the agent without the chat being able to move money.

The explanations it relays are the deal agent's trace-based text, so the
numbers quoted in chat are the numbers that were paid.

## Installing

1. Start the Edition Deal Agent API on the host (see the main README).
2. Copy `edition_deal_skills.py` somewhere on OmegaClaw's Python path.
   The OmegaClaw guide puts skill modules in a folder next to `src/`
   (`agentverse/` in its example); a sibling `edition_deals/` folder
   works the same way. Adjust the module path in the bridges to match.
3. Add the six `(= ...)` bridges from `skills.metta` to OmegaClaw's
   `src/skills.metta`, and the six description lines to the list that
   `getSkills` returns.
4. Tell the skills where the API is. From inside OmegaClaw's container
   the host is usually reachable as `host.docker.internal`:

   ```
   EDA_API_BASE=http://host.docker.internal:8000
   ```

   Pass it with `docker run -e EDA_API_BASE=...`, or set it in the
   container's environment.
5. Restart OmegaClaw (`docker start omegaclaw`) and ask it something like
   "Why did Print Studio D get paid for evt-deal-1-0002?"

The module uses only the Python standard library, so nothing needs
installing in the container.

## What has been tested

The Python functions have been run against the live API (every skill,
including unreachable-API and unknown-sale errors). The MeTTa bridges
follow the `py-call` pattern in OmegaClaw's published skill guide but
haven't yet been run inside OmegaClaw itself. Check the exact file layout
against the OmegaClaw version you install from the BASIX.MARKET resources.
