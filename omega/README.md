# Omega plugin

`edition_deals/` is a plugin for **Omega v0.1.20** (`singularitynet/omega`)
that lets the Omega agent talk about edition deals in chat: what's in
force, who was paid what and why, and which resales skipped the royalty.

| Skill | What it does |
|---|---|
| `(deal-status)` | Every deal, its newest version and the version in force |
| `(recent-sales)` | The latest sales in the ledger and who was paid what |
| `(explain-payout "sale-id" "party-id")` | The deal agent's own answer to "why did they get this?" |
| `(scan-royalties)` | Runs the watch and reports what needs a look |
| `(open-flags)` | Open flags, each with its evidence |
| `(check-deal "{...json...}")` | Checks a draft deal against every rule without saving it |

It uses Omega's plugin API (`docs/reference-plugin-api.md` in the Omega
repo): `edition_deals.metta` has a `loadOmegaPlugin` entry point that
registers the skills with `add-skill`, and each skill `py-call`s
`edition_deal_skills.py`, which calls the deal agent's HTTP API. The Python
side uses only the standard library.

## Wiring it up

You need the deal agent's API running on this machine (main README,
**Setup**). Then, in the Ubuntu (WSL) terminal, where `docker` works:

```bash
cd /mnt/c/Users/Admin/Documents/SOTA-OCT-26
bash omega/install.sh              # container name defaults to "omega"
docker restart omega
docker logs -f omega | grep -E "edition|plugin"
```

The log should show `Edition Deal Agent API: http://host.docker.internal:8000`
and `Plugin edition_deals is loaded`. Then ask the bot on Telegram, for
example: *"Why did Print Studio D get paid for sale evt-deal-1-0002?"*

### Where the API is

The plugin reads Omega's `edaApiBase` setting, defaulting to
`http://host.docker.internal:8000`. Omega's container already maps
`host.docker.internal` to this machine, and the deal agent's API can stay
bound to `127.0.0.1`. To point elsewhere, set `edaApiBase` the Omega way:
as `edaApiBase=http://...` on Omega's command line, or in
`config/config.yaml`.

An environment variable won't work: Omega starts its agent with a scrubbed
environment. That's why the address is passed from MeTTa into every
Python call.

### Keeping it across container rebuilds

`install.sh` copies files into the existing container. If you recreate the
container (for example by re-running Omega's setup script), run it again,
or mount the plugin instead by adding these to your `docker run` command:

```bash
-v /mnt/c/Users/Admin/Documents/SOTA-OCT-26/omega/edition_deals:/PeTTa/repos/Omega/plugins/edition_deals:ro
-v /path/to/your/plugins.yaml:/PeTTa/repos/Omega/config/plugins.yaml:ro
```

where your `plugins.yaml` is Omega's own plus:

```yaml
- name: edition_deals
  loader: metta
  location: "{REPO}/plugins/edition_deals"
```

### Removing it

Delete the `edition_deals` entry from `config/plugins.yaml` in the
container and restart it.

## What it can and can't do

The six skills only read, check and run the watch. None of them approves,
locks, records a sale or resets anything, and the explanations they relay
are the deal agent's own trace-based text, so the numbers quoted in chat
are the numbers paid.

**Not enforced yet:** Omega also has general skills, such as `shell`, that
plugins can't remove. In this demo the deal agent's write endpoints
(approve, lock, sales, `/sim/*`) have no authentication, so a shell
command inside Omega's container could still call them. Closing that means
requiring an operator token on those endpoints, kept out of Omega's
container.

## What has been tested

- The plugin was loaded by Omega v0.1.20's own plugin loader, from the
  `singularitynet/omega:v0.1.20` image in a throwaway container. All six
  skills appeared in the skill list Omega gives its LLM.
- Each skill was called through `py-call` against the running API and
  returned the expected text, including the error for an unknown sale.
- The address `host.docker.internal:8000` reaches the API from the
  container.
- Not yet tested: a live Telegram conversation, where the LLM chooses the
  skill itself.
