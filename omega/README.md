# Omega in the app

People only use the React app. Its **Ask the agent** panel is a chat with
**Omega v0.1.20** (`singularitynet/omega`), which answers using the deal
agent's own skills:

```
React app ──► deal agent API ◄──websocket── Omega ──► OpenAI (reads the question, picks a skill)
 "Ask the agent"   /assistant/*      /omega/ws       │
                                                     └──skills──► deal agent API (the answers)
```

Omega connects *out* to the deal agent through its built-in `websocket`
chat channel (`channels/wschat.py` in Omega). The deal agent is the chat
server, so there's no Telegram and no separate chat account. Omega logs in
with a bearer token, `EDA_OMEGA_WS_TOKEN`, kept in `.env`.

## The plugin

`edition_deals/` is an Omega plugin (Omega's `docs/reference-plugin-api.md`).
`edition_deals.metta` has a `loadOmegaPlugin` entry point that registers
six skills with `add-skill`. It also adds a prompt section telling Omega it's
the assistant inside this app and that every amount must come from a skill.
Each skill `py-call`s `edition_deal_skills.py`, which calls the deal agent's
HTTP API using only the standard library.

| Skill | What it does |
|---|---|
| `(deal-status)` | Every deal, its newest version and the version in force |
| `(recent-sales)` | The latest sales in the ledger and who was paid what |
| `(explain-payout "sale-id" "party-id")` | The deal agent's own answer to "why did they get this?" |
| `(scan-royalties)` | Runs the watch and reports what needs a look |
| `(open-flags)` | Open flags, each with its evidence |
| `(check-deal "{...json...}")` | Checks a draft deal against every rule without saving it |

The plugin reads the API's address from Omega's `edaApiBase` setting
(default `http://host.docker.internal:8000`). It can't use an environment
variable, because Omega starts its agent with a scrubbed environment.

## Switching your Omega container to the app

1. Start the deal agent's API on this machine (main README, **Setup**).
   It reads `EDA_OMEGA_WS_TOKEN` from `.env`.
2. In the Ubuntu (WSL) terminal, where `docker` works:

   ```bash
   cd /mnt/c/Users/Admin/Documents/SOTA-OCT-26
   bash omega/use_web_chat.sh
   ```

   The script:
   - reads the token from `.env`, creating one if it's missing;
   - copies your `omega` container's image, Omega options, memory volume,
     run options and environment (API keys go to a private temp file, are
     never printed, and are deleted afterwards);
   - writes `var/omega/plugins.yaml` (Omega's own list plus `edition_deals`);
   - stops your `omega` container and keeps it as `omega-telegram-backup`;
   - starts a new `omega` with `commchannel=websocket`, `WS_URL`, `WS_TOKEN`
     and the plugin mounted read-only from this repo.
3. Open the app. The **Ask the agent** button's dot turns green once Omega
   connects, and Omega posts its version in the chat. To follow it in the
   log instead:

   ```bash
   docker logs -f omega 2>&1 | grep -E "edition|plugin|websocket|Connected"
   ```

   You should see `Plugin edition_deals is loaded`.

Because the plugin is mounted from this repo, a change to it only needs
`docker restart omega`.

**Undo** (back to Telegram):

```bash
docker rm -f omega && docker rename omega-telegram-backup omega && docker start omega
```

## Behaviour

- Messages typed while Omega is offline wait in the deal agent and are
  delivered when it connects. A freshly started Omega isn't re-sent old
  questions.
- The app refuses messages starting with `/`, which Omega's channels treat
  as operator commands (for example `/memory-export`).
- Everyone using the app shares one conversation with Omega.

## What it can and can't do

The six skills only read, check and run the watch: none of them approves,
locks, records a sale or resets anything. The explanations they relay are
the deal agent's trace-based text, so the numbers quoted in the chat are
the numbers paid.

**Not enforced yet:** Omega also has general skills that plugins can't
remove, such as `shell` and file access, and anyone using the app can ask
Omega anything. In this demo the deal agent's write endpoints (approve,
lock, sales, `/sim/*`) have no authentication, so Omega could still reach
them through `shell`. Keep the app on this machine (it binds to
`127.0.0.1`). The next step is an operator token on those endpoints, kept
out of Omega's container.

## What has been tested

- The plugin was loaded by Omega v0.1.20's own loader in a throwaway
  container from your image. The six skills and the prompt section
  registered, and each skill answered from the running API.
- Omega's real `wschat.py` adapter, run from your image, connected to
  `/omega/ws` with the token and was refused (HTTP 403) with a wrong one. It
  received a question that was waiting from before it connected, and its
  reply reached the app.
- `use_web_chat.sh` was run on a stand-in container shaped like yours, with
  a fake OpenAI key. The new container kept the image, options, volume and
  environment. Omega started, connected by itself, and posted
  `Omega version=v0.1.20` to the chat.
- The **Ask the agent** panel was driven in a browser against a stand-in
  that answered with the plugin's skills.
- `tests/test_assistant.py` plays Omega's side of the protocol.
- **Not yet tested:** your real Omega answering in the app, where gpt-5.5
  picks the skill itself.
