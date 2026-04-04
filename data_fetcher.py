"""
Pelosi Algo Trader — Data Fetcher
==================================
Pulls congressional trade disclosures and stock price data.

Data Sources:
1. House Stock Watcher (free JSON feed of all House trades)
2. Yahoo Finance (free stock price data)
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import re

import requests
from bs4 import BeautifulSoup

from config import (
    TRACKED_POLITICIANS,
    HOUSE_STOCK_WATCHER_URL,
    CAPITOL_TRADES_URL,
    YAHOO_FINANCE_BASE,
    DATA_DIR,
    FRESHNESS_WINDOW_DAYS,
    DISCLOSURE_DELAY_MAX_DAYS,
)


def ensure_data_dir():
    """Create data directory if it doesn't exist."""
    os.makedirs(DATA_DIR, exist_ok=True)


# ── CONGRESSIONAL TRADE DATA ───────────────────────────────────────

def _parse_capitol_trades_amount(value_text: str) -> str:
    """Convert CapitolTrades value text like '$1M–$5M' to House Stock Watcher format."""
    amount_map = {
        "1k–15k": "$1,001 - $15,000",
        "15k–50k": "$15,001 - $50,000",
        "50k–100k": "$50,001 - $100,000",
        "100k–250k": "$100,001 - $250,000",
        "250k–500k": "$250,001 - $500,000",
        "500k–1m": "$500,001 - $1,000,000",
        "1m–5m": "$1,000,001 - $5,000,000",
        "5m–25m": "$5,000,001 - $25,000,000",
        "25m–50m": "$25,000,001 - $50,000,000",
    }
    cleaned = value_text.replace("$", "").replace(" ", "").lower()
    return amount_map.get(cleaned, value_text)


def _parse_date_from_cells(cell) -> str:
    """Parse date from CapitolTrades date cell (has day/month + year in separate divs)."""
    divs = cell.select("div.text-center div")
    if len(divs) >= 2:
        day_month = divs[0].get_text(strip=True)  # e.g. "26 Jan"
        year = divs[1].get_text(strip=True)        # e.g. "2026"
        try:
            return datetime.strptime(f"{day_month} {year}", "%d %b %Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def _fetch_from_capitol_trades() -> list[dict]:
    """
    Scrape trade data from CapitolTrades for tracked politicians.
    Returns trades in House Stock Watcher compatible format.
    """
    all_trades = []
    headers = {"User-Agent": "Mozilla/5.0"}

    for politician_id, name in [("P000197", "Nancy Pelosi")]:
        for page in range(1, 4):  # First 3 pages
            url = f"https://www.capitoltrades.com/trades?politician={politician_id}&page={page}"
            try:
                resp = requests.get(url, headers=headers, timeout=30)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")

                rows = soup.select("table tbody tr")
                if not rows:
                    break

                for row in rows:
                    cells = row.select("td")
                    if len(cells) < 9:
                        continue

                    # Cell 1: issuer — ticker is in issuer-info after the name
                    issuer_cell = cells[1]
                    issuer_text = issuer_cell.get_text(" ", strip=True)
                    # Extract ticker (format like "AB:US" or "GOOGL:US")
                    ticker_match = re.search(r'\b([A-Z]{1,5}):US\b', issuer_text)
                    ticker = ticker_match.group(1) if ticker_match else ""
                    # Extract company name from the <a> tag
                    name_link = issuer_cell.select_one("a")
                    asset_desc = name_link.get_text(strip=True) if name_link else ""

                    # Cell 2: published date, Cell 3: traded date
                    pub_date = _parse_date_from_cells(cells[2])
                    tx_date = _parse_date_from_cells(cells[3])

                    # Cell 5: owner
                    owner_text = cells[5].get_text(strip=True).lower()

                    # Cell 6: transaction type (buy/sell)
                    tx_type_el = cells[6].select_one(".tx-type")
                    tx_type_text = tx_type_el.get_text(strip=True).lower() if tx_type_el else ""
                    if "buy" in tx_type_text:
                        tx_type = "purchase"
                    elif "sell" in tx_type_text:
                        tx_type = "sale_full"
                    else:
                        tx_type = tx_type_text

                    # Cell 7: trade size — get the text from the tooltip wrapper
                    size_el = cells[7].select_one(".trade-size")
                    if size_el:
                        # The actual range text may be in a tooltip; fall back to body text
                        size_text = size_el.get_text(strip=True)
                    else:
                        size_text = cells[7].get_text(strip=True)
                    amount = _parse_capitol_trades_amount(size_text)

                    # Use Paul Pelosi if owner is "spouse"
                    rep_name = "Paul Pelosi" if "spouse" in owner_text else name

                    trade = {
                        "representative": rep_name,
                        "transaction_date": tx_date,
                        "disclosure_date": pub_date,
                        "ticker": ticker,
                        "asset_description": asset_desc,
                        "type": tx_type,
                        "amount": amount,
                    }
                    if ticker and tx_date:
                        all_trades.append(trade)

            except Exception as e:
                print(f"   ⚠️  CapitolTrades page {page} error: {e}")
                break

            time.sleep(1)  # Rate limiting

    return all_trades


def fetch_all_house_trades() -> list[dict]:
    """
    Fetch House trading disclosures. Tries multiple sources:
    1. CapitolTrades (primary - scrapes HTML)
    2. House Stock Watcher S3 (legacy, may be down)
    3. Local cache
    4. Sample data (demo mode)
    """
    # Try CapitolTrades first
    print("📡 Fetching congressional trade disclosures from CapitolTrades...")
    trades = _fetch_from_capitol_trades()
    if trades:
        print(f"   ✅ Got {len(trades)} trades from CapitolTrades")
        return trades

    # Try legacy House Stock Watcher
    print("   ⚠️  CapitolTrades unavailable, trying House Stock Watcher...")
    try:
        resp = requests.get(HOUSE_STOCK_WATCHER_URL, timeout=30)
        resp.raise_for_status()
        trades = resp.json()
        print(f"   ✅ Got {len(trades)} total House trades")
        return trades
    except Exception as e:
        print(f"   ⚠️  House Stock Watcher also unavailable: {e}")

    # Fall back to cached data
    cache_path = os.path.join(DATA_DIR, "all_trades_cache.json")
    if os.path.exists(cache_path):
        print("   📂 Using cached trade data")
        with open(cache_path) as f:
            return json.load(f)

    # Fall back to sample data for demo
    sample_path = os.path.join(DATA_DIR, "sample_trades.json")
    if os.path.exists(sample_path):
        print("   📂 Using sample trade data (demo mode)")
        with open(sample_path) as f:
            return json.load(f)

    return []


def cache_trades(trades: list[dict]):
    """Save trades to local cache."""
    ensure_data_dir()
    cache_path = os.path.join(DATA_DIR, "all_trades_cache.json")
    with open(cache_path, "w") as f:
        json.dump(trades, f)


def filter_pelosi_trades(all_trades: list[dict]) -> list[dict]:
    """
    Filter trades to only those by tracked politicians (Pelosi family).
    Also filters for recent trades within the freshness window.
    """
    pelosi_trades = []
    cutoff_date = datetime.now() - timedelta(days=FRESHNESS_WINDOW_DAYS + DISCLOSURE_DELAY_MAX_DAYS)

    for trade in all_trades:
        representative = trade.get("representative", "")
        # Check if this is a Pelosi trade
        if not any(name.lower() in representative.lower() for name in TRACKED_POLITICIANS):
            continue

        # Parse the transaction date
        tx_date_str = trade.get("transaction_date", "")
        try:
            tx_date = datetime.strptime(tx_date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            continue

        if tx_date >= cutoff_date:
            trade["_parsed_date"] = tx_date
            pelosi_trades.append(trade)

    # Sort by date, most recent first
    pelosi_trades.sort(key=lambda t: t["_parsed_date"], reverse=True)
    print(f"🎯 Found {len(pelosi_trades)} recent Pelosi-family trades")
    return pelosi_trades


def parse_trade_amount(amount_str: str) -> tuple[float, float]:
    """
    Parse trade amount ranges like '$1,001 - $15,000' into (low, high).
    """
    if not amount_str:
        return (0, 0)
    # Clean up the string
    cleaned = amount_str.replace("$", "").replace(",", "").strip()
    if " - " in cleaned:
        parts = cleaned.split(" - ")
        try:
            return (float(parts[0].strip()), float(parts[1].strip()))
        except ValueError:
            return (0, 0)
    try:
        val = float(cleaned)
        return (val, val)
    except ValueError:
        return (0, 0)


def normalize_pelosi_trade(trade: dict) -> dict:
    """
    Convert raw trade data into a clean, standardized format.
    """
    amount_low, amount_high = parse_trade_amount(trade.get("amount", ""))
    tx_type = trade.get("type", "").lower()

    # Determine if this is a buy or sell signal for us
    if "purchase" in tx_type:
        action = "BUY"
    elif "sale" in tx_type:
        action = "SELL"
    else:
        action = "UNKNOWN"

    return {
        "ticker": trade.get("ticker", "N/A"),
        "action": action,
        "amount_low": amount_low,
        "amount_high": amount_high,
        "transaction_date": trade.get("transaction_date", ""),
        "disclosure_date": trade.get("disclosure_date", ""),
        "representative": trade.get("representative", ""),
        "asset_description": trade.get("asset_description", ""),
        "type": trade.get("type", ""),
        "raw": trade,
    }


# ── STOCK PRICE DATA ──────────────────────────────────────────────

def fetch_stock_price(ticker: str) -> Optional[dict]:
    """
    Fetch current stock data from Yahoo Finance.
    Returns dict with price, change, volume, etc.
    """
    if not ticker or ticker == "N/A" or ticker == "--":
        return None

    try:
        url = f"{YAHOO_FINANCE_BASE}{ticker}"
        params = {
            "interval": "1d",
            "range": "1mo",
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        result = data.get("chart", {}).get("result", [])
        if not result:
            return None

        meta = result[0].get("meta", {})
        indicators = result[0].get("indicators", {}).get("quote", [{}])[0]
        timestamps = result[0].get("timestamp", [])

        closes = indicators.get("close", [])
        volumes = indicators.get("volume", [])
        highs = indicators.get("high", [])
        lows = indicators.get("low", [])

        if not closes or len(closes) < 2:
            return None

        current_price = meta.get("regularMarketPrice", closes[-1])
        prev_close = closes[-2] if len(closes) >= 2 else current_price

        # Calculate momentum (5-day and 20-day returns)
        five_day_return = None
        twenty_day_return = None
        if len(closes) >= 6:
            if closes[-6] and closes[-1]:
                five_day_return = (closes[-1] - closes[-6]) / closes[-6]
        if len(closes) >= 21:
            if closes[-21] and closes[-1]:
                twenty_day_return = (closes[-1] - closes[-21]) / closes[-21]

        # Average volume
        valid_volumes = [v for v in volumes if v]
        avg_volume = sum(valid_volumes) / len(valid_volumes) if valid_volumes else 0

        return {
            "ticker": ticker,
            "current_price": current_price,
            "prev_close": prev_close,
            "day_change_pct": ((current_price - prev_close) / prev_close * 100) if prev_close else 0,
            "five_day_return": five_day_return,
            "twenty_day_return": twenty_day_return,
            "avg_volume": avg_volume,
            "latest_volume": volumes[-1] if volumes else 0,
            "fifty_two_week_high": meta.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": meta.get("fiftyTwoWeekLow"),
            "closes": closes,
            "timestamps": timestamps,
        }
    except Exception as e:
        print(f"   ⚠️  Could not fetch price for {ticker}: {e}")
        return None


def fetch_historical_prices(ticker: str, start_date: str, days_forward: int = 90) -> Optional[dict]:
    """
    Fetch historical daily closes for a ticker starting from a date.
    Returns dict with dates and closes for calculating post-trade returns.
    """
    if not ticker or ticker in ("N/A", "--"):
        return None

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = start_dt + timedelta(days=days_forward + 5)  # extra buffer for weekends
        period1 = int(start_dt.timestamp())
        period2 = int(end_dt.timestamp())

        url = f"{YAHOO_FINANCE_BASE}{ticker}"
        params = {"interval": "1d", "period1": period1, "period2": period2}
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        result = data.get("chart", {}).get("result", [])
        if not result:
            return None

        timestamps = result[0].get("timestamp", [])
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])

        if not closes or not timestamps:
            return None

        # Build date->close mapping
        daily = []
        for ts, close in zip(timestamps, closes):
            if close is not None:
                daily.append({"date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"), "close": close})

        return {"ticker": ticker, "daily": daily}
    except Exception as e:
        print(f"   ⚠️  Could not fetch historical prices for {ticker}: {e}")
        return None


def fetch_prices_for_tickers(tickers: list[str]) -> dict:
    """
    Fetch price data for a list of tickers. Returns {ticker: price_data}.
    Adds a small delay between requests to be polite to Yahoo.
    """
    prices = {}
    for ticker in tickers:
        if ticker and ticker != "N/A" and ticker != "--":
            price_data = fetch_stock_price(ticker)
            if price_data:
                prices[ticker] = price_data
            time.sleep(0.5)  # Rate limiting
    return prices


# ── MAIN FETCH PIPELINE ───────────────────────────────────────────

def get_pelosi_signals() -> list[dict]:
    """
    Main entry point: fetch trades, filter for Pelosi, normalize,
    and enrich with current price data.
    """
    ensure_data_dir()

    # 1. Get all House trades
    all_trades = fetch_all_house_trades()
    if all_trades:
        cache_trades(all_trades)

    # 2. Filter for Pelosi
    pelosi_raw = filter_pelosi_trades(all_trades)

    # 3. Normalize
    signals = [normalize_pelosi_trade(t) for t in pelosi_raw]
    signals = [s for s in signals if s["ticker"] != "N/A" and s["action"] != "UNKNOWN"]

    # 4. Get unique tickers and fetch prices
    tickers = list(set(s["ticker"] for s in signals))
    print(f"💰 Fetching prices for {len(tickers)} tickers...")
    prices = fetch_prices_for_tickers(tickers)

    # 5. Attach price data to signals
    for signal in signals:
        signal["price_data"] = prices.get(signal["ticker"])

    print(f"✅ Pipeline complete: {len(signals)} actionable Pelosi signals")
    return signals


if __name__ == "__main__":
    signals = get_pelosi_signals()
    for s in signals[:5]:
        print(f"\n{'='*50}")
        print(f"  {s['action']} {s['ticker']} — {s['asset_description']}")
        print(f"  Date: {s['transaction_date']}  |  Amount: ${s['amount_low']:,.0f}-${s['amount_high']:,.0f}")
        if s.get("price_data"):
            p = s["price_data"]
            print(f"  Current: ${p['current_price']:.2f}  |  Day: {p['day_change_pct']:+.1f}%")
