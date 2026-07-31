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

class GenerateImageSkill(Skill):
    name = "generate_image"
    description = "Generate an AI image from a text prompt and display it."

    async def execute(self, prompt: str, **kwargs) -> SkillResult:
        try:
            import urllib.parse
            import urllib.request
            import os
            from pathlib import Path

            encoded_prompt = urllib.parse.quote(prompt)
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            
            save_path = Path.home() / "Desktop" / "LIS_Generated_Image.jpg"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response, open(save_path, 'wb') as out_file:
                out_file.write(response.read())
            
            # Open the image natively on Windows
            import subprocess
            subprocess.Popen(f'explorer.exe "{save_path}"', shell=True)
            
            return SkillResult(True, f"Image generated and opened, sir.")
        except Exception as e:
            return SkillResult(False, f"Image generation error: {e}")
registry.register(GenerateImageSkill())

class FunSkill(Skill):
    name = "fun_action"
    description = "Flip a coin, roll a dice, or tell a joke."

    async def execute(self, type: str, **kwargs) -> SkillResult:
        import random
        if type == "flip_coin":
            res = random.choice(["Heads", "Tails"])
            return SkillResult(True, f"It's {res}, sir.")
        elif type == "roll_dice":
            res = random.randint(1, 6)
            return SkillResult(True, f"You rolled a {res}, sir.")
        elif type == "joke":
            jokes = [
                "Why don't scientists trust atoms? Because they make up everything.",
                "What do you call a fake noodle? An Impasta.",
                "I told my computer I needed a break, and now it won't stop sending me KitKats.",
                "Why did the programmer quit his job? Because he didn't get arrays.",
                "What's a computer's favorite snack? Microchips.",
                "Why do Java developers wear glasses? Because they can't C-sharp."
            ]
            return SkillResult(True, random.choice(jokes))
        elif type == "fact":
            facts = [
                "A group of flamingos is called a flamboyance.",
                "Honey never spoils. Archaeologists have found 3000-year-old honey that was still edible.",
                "Octopuses have three hearts and blue blood.",
                "The inventor of the Pringles can is buried in one.",
                "A day on Venus is longer than a year on Venus."
            ]
            return SkillResult(True, f"Here's a fun fact: {random.choice(facts)}")
        return SkillResult(False, "Invalid fun type, sir.")


# Adaptive Learning Tracker
registry.register(FunSkill())

