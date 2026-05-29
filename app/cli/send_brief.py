"""
CLI entry: run daily brief.
Usage:
    python -m app.cli.send_brief
"""
import asyncio
from app.services.daily_brief import run_daily_brief


if __name__ == "__main__":
    result = asyncio.run(run_daily_brief())
    print(f"Done: {result}")
