# AI disclosure

The hackathon rules allow AI use and require it to be disclosed. This is
what we used and what for. It's kept up to date as the project changes.

## Tools

| Tool | Used for |
|---|---|
| **Claude Code** (Anthropic; model Claude Opus 5.5), in VS Code | See below. Most of the code and documentation in this repo was written by Claude Code, working with a team member who directed the work, made the decisions and reviewed the results. |
| **Omega** v0.1.20 (SingularityNET), with **OpenAI gpt-5.5** as its language model | A chat agent (on Telegram) that calls the deal agent's read-only skills through the plugin in `omega/`. The language model reads questions and picks a skill. It has no part in any check, payout or classification. |

## What Claude Code did

- Read the hackathon starter repo and track brief, and helped plan the build within Track 02, challenge 6.
- Asked clarifying questions about the build brief. The team's answers became the decisions recorded in the README.
- Wrote the MeTTa rules (`rules/`), the Python service layer, the chain simulator and storage (`agent/`), the API (`api/`), the React app (`web/`) and the Omega plugin and installer (`omega/`).
- Wrote the tests (`tests/`), ran them, and fixed what failed.
- Wrote the placeholder data (`data/`): the invented artwork, parties and wallets, the plain-words agreement, the sample deals, and the **inputs** of the golden scenarios.
- Ran the app and drove it in a headless browser to check each screen, then fixed the layout problems it found.
- Wrote the README, `data/README.md`, `omega/README.md` and this file.

## What people did

- The project idea and the build brief: written by the team. (Team: note here if you used AI to help draft it.)
- Every decision in the README's Decisions section, including the list of contradictions the agent checks.
- The **answers** in `data/golden_scenarios.csv` are worked out by hand, without the code, so they are an independent check on it. AI did not fill them in.
- Installing Omega and connecting it to Telegram and OpenAI. (Claude Code inspected the installed container, read-only, to fit the plugin to Omega v0.1.20, and tested it in throwaway containers.)
- Reviewing the work, recording the demo video, and submitting on BASIX.MARKET.

## AI inside the product

The deal agent itself uses **no** machine-learning model. Every check,
payout and classification is made by the MeTTa rules in `rules/`, and
every explanation is a template filled in from those rules' trace. The
only model involved is Omega's (gpt-5.5). The skills our plugin gives it
only read, check and run the watch; [omega/README.md](omega/README.md)
explains what isn't enforced yet.
