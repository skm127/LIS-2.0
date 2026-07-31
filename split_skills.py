import os
import re
import sys

# Idempotency guard: don't re-split if already split
with open('skills.py', 'r', encoding='utf-8') as _f:
    _content = _f.read()
    if 'class LaunchAppSkill(Skill):' not in _content:
        print("Skills already split. Nothing to do.")
        sys.exit(0)

with open('skills.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

start_idx = 0
for i, line in enumerate(lines):
    if 'class LaunchAppSkill(Skill):' in line:
        start_idx = i
        break

base_lines = lines[:start_idx]
while base_lines[-1].startswith('#'):
    base_lines.pop()

with open('skills.py', 'w', encoding='utf-8') as f:
    f.writelines(base_lines)

os.makedirs('plugins/core', exist_ok=True)

header = """from skills import Skill, SkillResult, registry
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

"""

file_mapping = {
    'system.py': ['LaunchAppSkill', 'SystemPowerSkill', 'SystemKeysSkill', 'ComputerControlSkill'],
    'media.py': ['VolumeControlSkill', 'BrightnessControlSkill', 'MediaControlSkill', 'MusicSkill'],
    'productivity.py': ['TimerSkill', 'AlarmSkill', 'ReminderSkill', 'ManageListSkill', 'TeachingSkill', 'SuggestionsSkill', 'AdaptiveLearningSkill'],
    'web.py': ['WikipediaSkill', 'WebSearchSkill', 'AutoSearchSkill', 'NewsSkill', 'GoogleMapsSkill'],
    'tools.py': ['CalculatorSkill', 'UnitConverterSkill', 'TranslatorSkill', 'CurrencyConverterSkill', 'DictionarySkill', "DateTimeSkill"],
    'vision.py': ['VisionSkill', 'TakeScreenshotSkill', 'DescribeScreenSkill', 'WebcamCaptureSkill'],
    'fun.py': ['FunSkill', 'GenerateImageSkill'],
    'finance.py': ['StockPriceSkill', 'CryptoPriceSkill', 'MarketSummarySkill', 'FinanceSkill'],
    'agents.py': ['SubAgentSkill', 'MCPActionSkill'],
    'smart_home.py': ['SmartHomeSkill'],
    'knowledge.py': ['KnowledgeGraphSkill', 'LocalDocumentSearchSkill'],
    'browser.py': ['BrowseEdgeSkill', 'SendEmailSkill', 'WhatsAppSkill']
}

class_to_file = {}
for filename, classes in file_mapping.items():
    for cls in classes:
        class_to_file[cls] = filename

for filename in file_mapping.keys():
    path = os.path.join('plugins', 'core', filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(header)

current_class = None
class_code = []

for line in lines[start_idx:]:
    match = re.match(r'^class\s+([A-Za-z0-9_]+)\(Skill\):', line)
    if match:
        if current_class:
            fname = class_to_file.get(current_class, 'misc.py')
            out_path = os.path.join('plugins', 'core', fname)
            if not os.path.exists(out_path):
                with open(out_path, 'w', encoding='utf-8') as f: f.write(header)
            with open(out_path, 'a', encoding='utf-8') as f:
                f.write(''.join(class_code).rstrip() + '\n')
                f.write(f"registry.register({current_class}())\n\n")
                
        current_class = match.group(1)
        class_code = [line]
    elif current_class:
        if line.startswith('registry.register(') or line.startswith('# ---') or line.startswith('# '):
            if not line.startswith('    #') and not line.startswith('        #'):
                if line.startswith('registry.register('):
                    continue
                if line.startswith('# ---') or (line.startswith('#') and 'Skill' in line):
                    continue
        class_code.append(line)

if current_class:
    fname = class_to_file.get(current_class, 'misc.py')
    out_path = os.path.join('plugins', 'core', fname)
    with open(out_path, 'a', encoding='utf-8') as f:
        f.write(''.join(class_code).rstrip() + '\n')
        f.write(f"registry.register({current_class}())\n\n")

print("Splitting complete.")
