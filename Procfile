web: cd backend && uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: cd backend && python scrapers/scheduler.py
clv: cd backend && python scrapers/clv_tracker.py
