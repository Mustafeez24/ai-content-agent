# AI Content Agent — FlyingFish Scuba School

An AI-powered content agent team for [FlyingFish Scuba School](https://www.instagram.com/flyingfishscuba) (Novotel Resort & Spa, Candolim, Goa), covering SSI & PADI scuba diving courses and experiences.

The system is being built incrementally into a team of five agents plus a dashboard and Telegram reporting:

1. **Content Scout / Ideator** — analyzes FlyingFish and competitor content, spots trends and content opportunities.
2. **Hook & Script Agent** — writes hooks, Reel scripts, captions, and CTAs.
3. **Content Planner** — builds daily/weekly content calendars around seasonality and bestsellers.
4. **Performance Analyst** — analyzes Instagram performance and recommends what to repeat or improve.
5. **DM/Enquiry Assistant** — categorizes enquiries, flags leads, and drafts responses.
6. **Dashboard** — a single view of all agent outputs, content ideas, analytics, calendar, and leads.
7. **Telegram Reporting** — daily AI reports and alerts sent straight to Telegram.

## Status

🚧 **Early setup stage.** Only the project scaffold exists so far — no agents are implemented yet. See `CLAUDE.md` for the current stage and development rules.

## Project structure

```
ai-content-agent/
├── backend/     # FastAPI app / core backend logic (to be built)
├── agents/      # Individual AI agent implementations (to be built)
├── dashboard/   # Web dashboard frontend (to be built)
├── scripts/     # One-off / utility scripts (e.g. Telegram sender, data pulls)
├── data/        # Local JSON/SQLite data (gitignored, not committed)
├── tests/       # Automated tests
└── docs/        # Additional documentation
```

## Tech stack (planned)

- **Backend / agents**: Python
- **API layer**: FastAPI (if/when needed)
- **Dashboard**: simple modern web frontend
- **AI**: Anthropic API (Claude)
- **Instagram / competitor data**: Apify
- **Reporting**: Telegram Bot API
- **Storage**: JSON / SQLite initially

The stack is intentionally kept simple and low-cost. No paid hosting or infrastructure is introduced without explicit discussion first.

## Getting started

1. Clone the repo and check out the working branch.
2. Copy `.env.example` to `.env` and fill in your own API keys locally (never commit `.env`).
3. Further setup instructions will be added as each component is built.

## Security

- Secrets are never hardcoded and never committed. See `.gitignore`.
- Required environment variables are documented (without values) in `.env.example`.
- No private customer data is committed to this repository.

## Development approach

This project is built incrementally, one step at a time, with testing and review at each stage. See `CLAUDE.md` for full development rules and current stage.
