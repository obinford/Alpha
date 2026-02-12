# RTM Picks Platform

## Project Overview
AI-powered sports betting intelligence platform hosted on Whop.
Covers MLB, NBA, NFL, NHL, CFB, CBB.
Features: +EV engine, proprietary prediction models, AI co-pilot, personalized bankroll management.

## Tech Stack
- Frontend: Next.js 14+ with TypeScript, Tailwind CSS, hosted on Vercel
- Backend: Python 3.11+ with FastAPI
- Database: Supabase (PostgreSQL with TimescaleDB extension)
- Cache: Upstash Redis
- Odds Data: The Odds API
- Stats Data: pybaseball (MLB), nba_api (NBA), nfl_data_py (NFL), NHL API
- AI: Claude API (Sonnet 4.5) for co-pilot features
- Auth/Payments: Whop SDK
- Hosting: Vercel (frontend), Supabase Edge Functions + Railway (backend workers)

## Project Structure
/frontend          - Next.js Whop app (TypeScript)
/backend           - Python FastAPI service
/backend/scrapers  - Data collection scripts (odds + stats)
/backend/models    - Betting prediction models + backtesting
/backend/api       - API endpoints
/shared            - Shared types and configuration
/scripts           - Utility scripts, database migrations

## Coding Standards
- Python: Type hints on all functions, docstrings, pytest for testing
- TypeScript: Strict mode, ESLint, Prettier
- All database queries use parameterized statements
- Every prediction model must have a backtest before deployment
- Use environment variables for all API keys and secrets (never hardcode)
- Write clear commit messages describing what changed and why

## Key Business Rules
- The +EV engine compares sportsbook odds to sharp book (Pinnacle/Circa) no-vig lines
- Positive EV = when a book's implied probability is lower than the true probability
- All picks must be timestamped and recorded for transparent performance tracking
- Closing Line Value (CLV) is the gold standard metric for proving edge
- Unit sizing follows Kelly Criterion (fractional Kelly for safety)

## Current Phase
Phase 1: Data infrastructure - odds pipeline + stats scrapers for MLB
