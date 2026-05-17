"""FastAPI app chính cho vpastock. Entry: uvicorn app.main:app --reload"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import settings
from app.api import stock, market, screener


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"VPASTOCK starting on {settings.APP_HOST}:{settings.APP_PORT}")
    logger.info(f"Environment: {settings.APP_ENV}")
    yield
    logger.info("VPASTOCK shutting down")


app = FastAPI(
    title="VPASTOCK API",
    description="API cho vpastock.com - app trading chứng khoán Việt Nam",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
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
