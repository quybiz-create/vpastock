"""Doc/ghi watchlist.json — { "Ten_danh_muc": ["FPT", "VIC"], ... }"""
import json
from pathlib import Path
from typing import Dict, List

WATCHLIST_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "watchlist.json"


def _normalize_ticker(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    if len(t) < 2 or len(t) > 10:
        raise ValueError("Ma co phieu khong hop le")
    return t


def _ensure_file() -> None:
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not WATCHLIST_PATH.exists():
        WATCHLIST_PATH.write_text("{}", encoding="utf-8")


def load_all() -> Dict[str, List[str]]:
    _ensure_file()
    with WATCHLIST_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for name, tickers in raw.items():
        if not isinstance(name, str) or not isinstance(tickers, list):
            continue
        out[name] = [_normalize_ticker(t) for t in tickers if isinstance(t, str) and t.strip()]
    return out


def save_all(data: Dict[str, List[str]]) -> None:
    _ensure_file()
    with WATCHLIST_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_names() -> List[str]:
    return list(load_all().keys())


def get_list(name: str) -> List[str]:
    data = load_all()
    if name not in data:
        raise KeyError(name)
    return list(data[name])


def set_list(name: str, tickers: List[str]) -> List[str]:
    if not name or not name.strip():
        raise ValueError("Ten danh muc khong hop le")
    normalized: List[str] = []
    seen = set()
    for t in tickers:
        sym = _normalize_ticker(t)
        if sym not in seen:
            seen.add(sym)
            normalized.append(sym)
    data = load_all()
    data[name.strip()] = normalized
    save_all(data)
    return normalized


def create_list(name: str, tickers: List[str] | None = None) -> List[str]:
    data = load_all()
    key = name.strip()
    if key in data:
        raise ValueError("Danh muc da ton tai")
    return set_list(key, tickers or [])


def delete_list(name: str) -> None:
    data = load_all()
    if name not in data:
        raise KeyError(name)
    del data[name]
    save_all(data)


def add_ticker(name: str, ticker: str) -> List[str]:
    sym = _normalize_ticker(ticker)
    data = load_all()
    if name not in data:
        data[name] = []
    if sym in data[name]:
        raise ValueError("Ma da co trong danh muc")
    data[name].append(sym)
    save_all(data)
    return data[name]


def remove_ticker(name: str, ticker: str) -> List[str]:
    sym = _normalize_ticker(ticker)
    data = load_all()
    if name not in data:
        raise KeyError(name)
    if sym not in data[name]:
        raise ValueError("Ma khong co trong danh muc")
    data[name] = [t for t in data[name] if t != sym]
    if not data[name]:
        del data[name]
    save_all(data)
    return data.get(name, [])
