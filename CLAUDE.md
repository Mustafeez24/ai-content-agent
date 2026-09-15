# CLAUDE.md — AI Content Agent (FlyingFish Scuba School)

This file gives Claude (and any future contributor) the context needed to work on this project correctly and safely.

## Project purpose

Build an AI Content Agent Team for **FlyingFish Scuba School**, a scuba diving school located at Novotel Resort & Spa, Candolim, Goa, offering SSI and PADI certifications and dive experiences. Instagram handle: `@flyingfishscuba`.

The system will eventually consist of five cooperating agents, a dashboard, and Telegram reporting:

1. **Content Scout / Ideator** — analyzes FlyingFish's own content and competitors' content, finds trends/topics, and recommends Reels/posts.
2. **Hook & Script Agent** — generates hooks, Reel scripts, captions, CTAs, and content angles.
3. **Content Planner** — builds daily/weekly content calendars accounting for seasonality, FlyingFish products, USPs, and bestsellers.
4. **Performance Analyst** — analyzes Instagram performance data and recommends what to repeat or improve.
5. **DM/Enquiry Assistant** — categorizes enquiries, identifies leads, drafts responses, and flags items needing human attention.
6. **Dashboard** — a single view showing all agents, their latest outputs, content ideas, analytics, calendar, and lead/DM insights.
7. **Telegram Reporting** — sends daily AI reports and important alerts, summarizing content opportunities and performance.

## FlyingFish business context

- Business: Scuba diving school / experiences.
- Certifications offered: SSI and PADI.
- Location: Novotel Resort & Spa, Candolim, Goa, India.
- Primary marketing channel: Instagram (`@flyingfishscuba`).
- Audience: tourists in Goa (domestic + international), beginners and certified divers.
- Business is seasonal — Goa's tourist season and diving conditions should factor into content planning once that agent is built.

## Architecture direction

- **Language**: Python for backend and agent logic.
- **API layer**: FastAPI, introduced only when an API is actually needed (e.g. to serve the dashboard).
- **Dashboard**: a simple, modern web frontend — kept lightweight, not over-engineered.
- **AI provider**: Anthropic API (Claude) for all agent reasoning/generation.
- **Instagram & competitor data**: Apify actors/API.
- **Reporting**: Telegram Bot API for daily reports and alerts.
- **Storage**: JSON files and/or SQLite initially. No heavier database is introduced until there's a genuine need.
- **Cost posture**: keep the system as inexpensive as possible. Prefer local development and free tiers. Any change that could introduce a cost (paid hosting, paid API tier, paid database, etc.) must be flagged to the project owner before being introduced.

Directory layout:

```
ai-content-agent/
├── backend/     # FastAPI app / shared backend logic
├── agents/      # Individual agent implementations (one agent per module/package)
├── dashboard/   # Web dashboard frontend
├── scripts/     # One-off/utility scripts (Telegram sender, data pulls, etc.)
├── data/        # Local JSON/SQLite data — gitignored, never committed
├── tests/       # Automated tests
└── docs/        # Additional documentation
```

## Security rules

- **Never hardcode secrets** (API keys, tokens, credentials) in source code, scripts, tests, or docs.
- All secrets live in a local `.env` file, which is **gitignored and never committed**.
- `.env.example` documents required variable names only, with empty/placeholder values.
- Never commit: `.env`, API keys, Telegram bot tokens, Apify tokens, credentials of any kind, or private customer data (e.g. real enquiry/DM content, phone numbers, emails).
- Never print secrets to terminal output, logs, or error messages.
- Never ask the project owner to paste secret keys into chat — they set them locally in `.env`.
- Treat any data pulled from Instagram DMs/enquiries as sensitive; do not commit sample data containing real customer information. Use anonymized/synthetic examples for tests and docs.

## Development rules

1. Work **one step at a time** — do not build multiple agents or large chunks of the system in a single pass.
2. Do not skip testing — after each step, run relevant checks (imports, basic script execution, linting, etc.) before considering it done.
3. Do not assume dependencies are installed — check the environment first, and explain why a new dependency is needed before adding it.
4. Reuse and extend existing files rather than replacing them unnecessarily.
5. Keep the architecture simple; avoid premature abstraction or speculative features.
6. Explain briefly what is being done at each step, and what the project owner needs to do next.
7. Before any architectural change (new service, new storage engine, new framework), explain the reasoning first.
8. Before introducing anything that could incur a cost, flag it explicitly and wait for confirmation.
9. Do not commit or push to GitHub without explicit confirmation from the project owner for that specific step.
10. Keep code and structure easy for another developer to pick up and understand — clear naming, minimal magic, no unnecessary comments.

## Current stage

**Stage 0 — Environment & project setup.**

Completed:
- Verified local environment (git, Python, Node, npm versions; repo state).
- Created base project structure (`backend/`, `agents/`, `dashboard/`, `scripts/`, `data/`, `tests/`, `docs/`).
- Added `.gitignore`, `.env.example`, `README.md`, and this `CLAUDE.md`.

Not yet started:
- No agents, backend API, dashboard, or Telegram integration have been implemented.
- No dependencies have been installed yet.
- No data (real or sample) has been collected or stored.

Next step will be defined by the project owner before any further code is written.
