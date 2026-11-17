# AegisOps // Predictive IT Infrastructure Maintenance

FastAPI + SQLite backend with two time-series forecasters (Holt-Winters and lag-feature Ridge regression) and a dark-mode NOC dashboard (Tailwind + Plotly via CDN).

## Run
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.main:app --reload   # run from inside this folder (the one containing backend/ and frontend/)
# or simply:  python run.py
```
Requires Python 3.9+. First load takes a few seconds while the database seeds and the first models fit.
Open http://127.0.0.1:8000. On first start the SQLite DB (`data/cluster_telemetry.db`) is created and seeded with 14 days of 5-minute telemetry for 4 servers. The browser needs internet access for the Tailwind/Plotly/Google Fonts CDNs.

## Dashboard tabs
Overview (KPIs, fleet cards, next actions), Forecast (plain-language summary, chart, model accuracy), Analysis (trends, days-to-limit, unusual spikes, daily pattern, correlation heatmap), Compare (all servers vs. safe limits), Tickets (filters, acknowledge/resolve, CSV export) and Guide. Header has Auto-play and a real-host-stats toggle.

## Structure
`backend/` (main, analysis, telemetry_engine, forecaster, ticket_manager, database), `frontend/` (index.html, styles.css, app.js).

## API
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/servers` | Health score, status, current metrics, TTF per server (also runs auto-ticketing) |
| GET | `/api/forecast/{server_id}?metric=memory_usage&hours=6` | 48h history, both forecasts, 95% band, MAE/RMSE/R² |
| POST | `/api/simulate/step?steps=3&live=false` | Advance 5-min ticks (3 = +15m); `live=true` reads host metrics via psutil for SRV-WEB-01 |
| POST | `/api/simulate/reset` | Regenerate the 14-day dataset |
| GET | `/api/analysis/{server_id}` | Trends, spikes, hourly pattern, correlation, plain-language insights |
| GET | `/api/compare?metric=cpu_usage` | Last 24h of every server as % of the safe limit |
| GET | `/api/tickets` | List tickets (`?status=open`) |
| POST | `/api/tickets/{id}/resolve` / `acknowledge` | Update ticket status |

## How it works
- **Holt-Winters**: additive trend + additive 288-step daily season on the last 4 days. If the seasonal fit fails, it falls back to damped trend, then seasonal-naive (shown in the evaluation table).
- **Lag regression**: Ridge on lags (1,2,3,6,12,288), rolling mean/std and time-of-day features, forecasting recursively.
- **Evaluation**: both are trained excluding the last 12h and scored on it (MAE, RMSE, R², accuracy = 100 − MAE/mean). The lower-RMSE model drives the confidence band (residual RMSE × 1.96, widening with horizon) and the chart breach note.
- **Fleet status and tickets** use the fast lag model over a 24h horizon on all four metrics. Thresholds: CPU 88%, memory 90%, disk latency 85 ms, temp 82 °C. A ticket is opened per server + metric when a breach is forecast; duplicates are suppressed while one is open or acknowledged, and tickets auto-close if the breach disappears.
- **Health score** blends proximity to each threshold with forecast time-to-failure (TTF).

## Notes
Simulated clocks advance independently of wall time, so stepping moves the cluster into the future. Use Reset to start over. Delete `data/cluster_telemetry.db` for a clean start.
