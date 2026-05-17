# VPASTOCK Backend

Backend FastAPI cho vpastock.com - app trading chứng khoán Việt Nam.

## Setup local trên Windows

```cmd
cd C:\
git clone <repo_url> vpastock
cd vpastock\backend

python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt

copy .env.example .env
```

Mở `.env` bằng Notepad, điền 2 giá trị:
- `ANTHROPIC_API_KEY` lấy từ console.anthropic.com
- `FIREANT_TOKEN` lấy từ F12 Network khi login fireant.vn

**KHÔNG paste 2 token này vào chat Claude.**

Chạy server:
```cmd
uvicorn app.main:app --reload --port 8000
```

Test:
- http://localhost:8000/health
- http://localhost:8000/docs (Swagger UI auto-generate)
- http://localhost:8000/api/stock/VIC/indicators

Mở `frontend/stock-detail.html` bằng Chrome.

## Cấu trúc

```
backend/
├── app/
│   ├── main.py              FastAPI entry point
│   ├── config.py            Đọc .env
│   ├── api/
│   │   ├── stock.py         Endpoints chính cho stock detail
│   │   ├── market.py        Market breadth, F&G (Phase 2)
│   │   └── screener.py      Bộ lọc (Phase 2)
│   ├── core/
│   │   └── indicators.py    MA, RSI, MACD, BB, ADX, Ichimoku, VPA
│   ├── data/
│   │   └── vnstock_client.py    Async wrapper cho vnstock
│   └── services/
│       └── ai_analyzer.py   Claude Haiku integration
├── scripts/
│   └── test_indicators.py   Test nhanh indicators
├── requirements.txt
└── .env.example
```

## API Endpoints (đã built)

| Method | Path | Mô tả |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/stock/{symbol}/history` | OHLCV lịch sử |
| GET | `/api/stock/{symbol}/indicators` | Giá + tất cả indicators |
| GET | `/api/stock/{symbol}/ai` | AI phân tích VPA + verdict |
| GET | `/api/stock/{symbol}/overview` | Thông tin công ty |
| GET | `/api/stock/{symbol}/financial` | P/E, P/B, ROE, ROA... |

## Roadmap

- Phase 1 (hiện tại): Stock Detail page với backend chạy ngon
- Phase 2: Market breadth, screener thật, watchlist CRUD
- Phase 3: Backtest engine, alert, mobile responsive
- Phase 4: Deploy production lên VPS Vietnix + vpastock.com
