from skills import Skill, SkillResult, registry
import asyncio
import logging
import time
import json
import difflib
import subprocess
import re
import memory
import ast
from typing import Optional, List, Dict, Callable, Any

log = logging.getLogger("LIS.plugins")

class CalculatorSkill(Skill):
    name = "calculate"
    description = "Evaluate a math expression safely."

    async def execute(self, expression: str, **kwargs) -> SkillResult:
        import math
        try:
            # Safe eval with math functions only
            allowed = {
                "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
                "pow": pow, "int": int, "float": float,
                "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
                "log": math.log, "log10": math.log10, "pi": math.pi, "e": math.e,
                "ceil": math.ceil, "floor": math.floor
            }
            try:
                tree = ast.parse(expression, mode='eval')
                result = eval(compile(tree, '<string>', 'eval'), {"__builtins__": {}}, allowed)
            except Exception as e:
                return SkillResult(False, f"Unsafe or invalid expression: {e}")
            return SkillResult(True, f"The result is {result}, sir.")
        except Exception as e:
            return SkillResult(False, f"I couldn't calculate that: {e}, sir.")
registry.register(CalculatorSkill())

class UnitConverterSkill(Skill):
    name = "convert_unit"
    description = "Convert between units (km to miles, kg to lbs, C to F, etc.)."

    CONVERSIONS = {
        ("km", "miles"): lambda x: x * 0.621371,
        ("miles", "km"): lambda x: x * 1.60934,
        ("kg", "lbs"): lambda x: x * 2.20462,
        ("lbs", "kg"): lambda x: x / 2.20462,
        ("celsius", "fahrenheit"): lambda x: x * 9/5 + 32,
        ("fahrenheit", "celsius"): lambda x: (x - 32) * 5/9,
        ("c", "f"): lambda x: x * 9/5 + 32,
        ("f", "c"): lambda x: (x - 32) * 5/9,
        ("meters", "feet"): lambda x: x * 3.28084,
        ("feet", "meters"): lambda x: x / 3.28084,
        ("liters", "gallons"): lambda x: x * 0.264172,
        ("gallons", "liters"): lambda x: x / 0.264172,
        ("cm", "inches"): lambda x: x / 2.54,
        ("inches", "cm"): lambda x: x * 2.54,
        ("grams", "ounces"): lambda x: x * 0.035274,
        ("ounces", "grams"): lambda x: x / 0.035274,
    }

    async def execute(self, value: float, from_unit: str, to_unit: str, **kwargs) -> SkillResult:
        try:
            value = float(value)
            key = (from_unit.lower(), to_unit.lower())
            if key in self.CONVERSIONS:
                result = self.CONVERSIONS[key](value)
                return SkillResult(True, f"{value} {from_unit} is {round(result, 4)} {to_unit}, sir.")
            return SkillResult(False, f"I don't know how to convert {from_unit} to {to_unit} yet, sir.")
        except Exception as e:
            return SkillResult(False, f"Conversion failed: {e}")
registry.register(UnitConverterSkill())

class TranslatorSkill(Skill):
    name = "translate"
    description = "Translate text between languages using free API."

    async def execute(self, text: str, to_lang: str = "en", from_lang: str = "auto", **kwargs) -> SkillResult:
        try:
            import httpx
            from urllib.parse import quote
            url = f"https://api.mymemory.translated.net/get?q={quote(text)}&langpair={from_lang}|{to_lang}"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    translated = data.get("responseData", {}).get("translatedText", "")
                    if translated:
                        return SkillResult(True, f"Translation: {translated}", data=translated)
            return SkillResult(False, "Translation service unavailable, sir.")
        except Exception as e:
            return SkillResult(False, f"Translation failed: {e}")
registry.register(TranslatorSkill())

class DateTimeSkill(Skill):
    name = "get_datetime"
    description = "Get current date, time, or timezone information."

    async def execute(self, query: str = "now", timezone: str = "", **kwargs) -> SkillResult:
        from datetime import datetime, timedelta
        import time as time_mod
        try:
            now = datetime.now()
            
            if "date" in query.lower():
                return SkillResult(True, f"Today is {now.strftime('%A, %B %d, %Y')}, sir.")
            elif "time" in query.lower():
                return SkillResult(True, f"The current time is {now.strftime('%I:%M %p')}, sir.")
            elif "day" in query.lower():
                return SkillResult(True, f"Today is {now.strftime('%A')}, sir.")
            elif "year" in query.lower():
                return SkillResult(True, f"The year is {now.year}, sir.")
            else:
                return SkillResult(True, f"It's {now.strftime('%A, %B %d, %Y at %I:%M %p')}, sir.")
        except Exception as e:
            return SkillResult(False, f"Date/time error: {e}")
registry.register(DateTimeSkill())

class CurrencyConverterSkill(Skill):
    name = "convert_currency"
    description = "Convert between currencies using live exchange rates."

    async def execute(self, amount: float, from_currency: str, to_currency: str, **kwargs) -> SkillResult:
        try:
            import httpx
            amount = float(amount)
            fr = from_currency.upper()
            to = to_currency.upper()
            url = f"https://api.exchangerate-api.com/v4/latest/{fr}"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    rates = resp.json().get("rates", {})
                    if to in rates:
                        result = amount * rates[to]
                        return SkillResult(True, f"{amount} {fr} is {round(result, 2)} {to}, sir.")
                    return SkillResult(False, f"Currency {to} not found, sir.")
            return SkillResult(False, "Exchange rate service unavailable, sir.")
        except Exception as e:
            return SkillResult(False, f"Currency conversion failed: {e}")
registry.register(CurrencyConverterSkill())

class DictionarySkill(Skill):
    name = "define_word"
    description = "Look up the definition of a word."

    async def execute(self, word: str, **kwargs) -> SkillResult:
        try:
            import httpx
            url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if data and isinstance(data, list):
                        meanings = data[0].get("meanings", [])
                        if meanings:
                            part = meanings[0].get("partOfSpeech", "")
                            defn = meanings[0].get("definitions", [{}])[0].get("definition", "")
                            return SkillResult(True, f"{word} ({part}): {defn}", data=defn)
            return SkillResult(False, f"I couldn't find a definition for {word}, sir.")
        except Exception as e:
            return SkillResult(False, f"Dictionary lookup failed: {e}")
registry.register(DictionarySkill())

