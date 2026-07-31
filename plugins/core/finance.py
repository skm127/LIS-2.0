from skills import Skill, SkillResult, registry
import asyncio
import logging
import time
import json
import difflib
import subprocess
import re
import memory
from typing import Optional, List, Dict, Callable, Any

log = logging.getLogger("LIS.plugins")

class StockPriceSkill(Skill):
    name = "get_stock"
    description = "Fetch real-time stock or index price."

    async def execute(self, symbol: str, **kwargs) -> SkillResult:
        try:
            import httpx
            symbol = symbol.upper().strip()

            # Common Indian aliases
            aliases = {
                "NIFTY": "^NSEI", "SENSEX": "^BSESN",
                "BANK NIFTY": "^NSEBANK", "BANKNIFTY": "^NSEBANK",
                "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS",
                "INFOSYS": "INFY.NS", "INFY": "INFY.NS",
                "HDFC": "HDFCBANK.NS", "WIPRO": "WIPRO.NS",
                "TATA MOTORS": "TATAMOTORS.NS", "ITC": "ITC.NS",
            }
            yahoo_symbol = aliases.get(symbol, symbol)
            # If no exchange suffix for Indian stocks, add .NS
            if not any(yahoo_symbol.startswith("^") or yahoo_symbol.endswith(s) for s in [".NS", ".BO", ".L", ".HK"]):
                # Check if it's likely a US stock or needs .NS
                pass

            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?interval=1d&range=5d"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    data = resp.json()
                    meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                    price = meta.get("regularMarketPrice", 0)
                    prev_close = meta.get("previousClose") or meta.get("chartPreviousClose", 0)
                    currency = meta.get("currency", "USD")
                    name = meta.get("shortName", symbol)

                    if price and prev_close:
                        change = price - prev_close
                        pct = (change / prev_close) * 100
                        direction = "up" if change > 0 else "down"
                        emoji = "📈" if change > 0 else "📉"
                        return SkillResult(True,
                            f"{emoji} {name} is at {currency} {price:.2f}, "
                            f"{direction} {abs(pct):.2f}% from yesterday's close of {prev_close:.2f}.")
                    elif price:
                        return SkillResult(True, f"{name} is currently at {currency} {price:.2f}.")

            return SkillResult(False, f"Couldn't fetch data for {symbol}, sir. Check the ticker symbol?")
        except Exception as e:
            log.error(f"Stock fetch failed: {e}")
            return SkillResult(False, f"Market data unavailable right now: {e}")
registry.register(StockPriceSkill())

class CryptoPriceSkill(Skill):
    name = "get_crypto"
    description = "Fetch real-time cryptocurrency price from CoinGecko."

    # Common aliases
    ALIASES = {
        "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
        "doge": "dogecoin", "xrp": "ripple", "ada": "cardano",
        "bnb": "binancecoin", "dot": "polkadot", "matic": "matic-network",
        "avax": "avalanche-2", "link": "chainlink", "shib": "shiba-inu",
        "ltc": "litecoin", "uni": "uniswap", "atom": "cosmos",
    }

    async def execute(self, coin: str, **kwargs) -> SkillResult:
        try:
            import httpx
            coin_id = self.ALIASES.get(coin.lower().strip(), coin.lower().strip())

            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd,inr&include_24hr_change=true"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if coin_id in data:
                        info = data[coin_id]
                        usd = info.get("usd", 0)
                        inr = info.get("inr", 0)
                        change_24h = info.get("usd_24h_change", 0)
                        emoji = "📈" if change_24h > 0 else "📉"
                        return SkillResult(True,
                            f"{emoji} {coin.upper()} is at ${usd:,.2f} (₹{inr:,.2f}), "
                            f"{'up' if change_24h > 0 else 'down'} {abs(change_24h):.2f}% in 24h.")

            return SkillResult(False, f"Couldn't find crypto data for {coin}.")
        except Exception as e:
            log.error(f"Crypto fetch failed: {e}")
            return SkillResult(False, f"Crypto data unavailable: {e}")
registry.register(CryptoPriceSkill())

class MarketSummarySkill(Skill):
    name = "market_summary"
    description = "Get a quick overview of major market indices."

    async def execute(self, **kwargs) -> SkillResult:
        try:
            import httpx
            indices = {
                "^NSEI": "Nifty 50",
                "^BSESN": "Sensex",
                "^GSPC": "S&P 500",
                "^DJI": "Dow Jones",
            }
            results = []
            async with httpx.AsyncClient(timeout=10.0) as client:
                for symbol, name in indices.items():
                    try:
                        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
                        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                        if resp.status_code == 200:
                            data = resp.json()
                            meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                            price = meta.get("regularMarketPrice", 0)
                            prev = meta.get("previousClose") or meta.get("chartPreviousClose", 0)
                            if price and prev:
                                pct = ((price - prev) / prev) * 100
                                emoji = "📈" if pct > 0 else "📉"
                                results.append(f"{emoji} {name}: {price:,.0f} ({pct:+.2f}%)")
                    except Exception:
                        continue

            if results:
                summary = ". ".join(results)
                return SkillResult(True, f"Market snapshot: {summary}.")

            return SkillResult(False, "Markets are closed or data is unavailable right now.")
        except Exception as e:
            log.error(f"Market summary failed: {e}")
            return SkillResult(False, f"Market data unavailable: {e}")
registry.register(MarketSummarySkill())

class FinanceSkill(Skill):
    """
    LIS 4.0 Financial Orchestration.
    Fetches cryptocurrency prices via CoinGecko.
    """
    name = "get_crypto_price"
    description = "Fetches the current price of a cryptocurrency in USD."

    async def execute(self, coin_id: str, **kwargs) -> SkillResult:
        try:
            import aiohttp
            clean_id = coin_id.lower().strip()
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={clean_id}&vs_currencies=usd"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if clean_id in data:
                            price = data[clean_id]["usd"]
                            return SkillResult(True, f"The current price of {coin_id} is ${price:,.2f} USD.")
                        else:
                            return SkillResult(False, f"Could not find price data for '{coin_id}'.")
                    else:
                        return SkillResult(False, f"CoinGecko API error: {resp.status}")
                        
        except ImportError:
            return SkillResult(False, "aiohttp is not installed.")
        except Exception as e:
            return SkillResult(False, f"Failed to fetch crypto price: {e}")
registry.register(FinanceSkill())

