"""Test scan sequential de tim ma gay crash."""
import sys
sys.path.insert(0, ".")

import asyncio
from app.data.symbol_list import HOSE_FALLBACK
from app.services.scanner import scan_one_symbol


async def main():
    symbols = HOSE_FALLBACK[:30]
    print(f"Scan {len(symbols)} ma sequential...")
    
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] Scanning {sym}...", flush=True)
        try:
            r = await scan_one_symbol(sym)
            if r:
                print(f"  OK price={r['price']} vpa={r.get('vpa')}")
            else:
                print(f"  None")
        except Exception as e:
            print(f"  ERROR: {e}")
    
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())