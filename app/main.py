"""FastAPI app chinh cho vpastock. Entry: uvicorn app.main:app --reload"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from app.config import settings
from app.db.database import init_db
from app.services.alert_scanner import scanner_loop
from app.api import stock, market, screener, calendar, risk, watchlist

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"VPASTOCK starting on {settings.APP_HOST}:{settings.APP_PORT}")
    logger.info(f"Environment: {settings.APP_ENV}")
    init_db()
    logger.info("Database initialized")
    import asyncio
    scanner_task = asyncio.create_task(scanner_loop())
    logger.info("Alert scanner started")
    yield
    scanner_task.cancel()
    logger.info("VPASTOCK shutting down")

app = FastAPI(
    title="VPASTOCK API",
    description="API cho vpastock.com - app trading chung khoan Viet Nam",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"name": "VPASTOCK API", "version": "1.0.0", "status": "ok", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "healthy", "env": settings.APP_ENV}
app.include_router(stock.router, prefix="/api/stock", tags=["stock"])
app.include_router(market.router, prefix="/api/market", tags=["market"])
app.include_router(screener.router, prefix="/api/screener", tags=["screener"])
app.include_router(calendar.router, prefix="/api/calendar", tags=["calendar"])
app.include_router(risk.router, prefix="/api/risk", tags=["risk"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])

