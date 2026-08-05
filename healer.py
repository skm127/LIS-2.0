"""
LIS Autonomous Healer
Monitors LIS errors and generates self-healing patches using LLMs.
"""

import os
import re
import time
import asyncio
from pathlib import Path
from datetime import datetime

# Load .env
from env_loader import load_env
load_env()

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("healer")

try:
    from llm_providers import LLMProviders
except ImportError:
    LLMProviders = None


class HealerDaemon:
    def __init__(self):
        self.error_log = Path(__file__).parent / "data" / "lis_errors.log"
        self.patches_dir = Path(__file__).parent / "data" / "patches"
        self.patches_dir.mkdir(parents=True, exist_ok=True)
        self.last_position = 0
        if self.error_log.exists():
            self.last_position = self.error_log.stat().st_size
        
        self.current_traceback = []
        self.in_traceback = False
        self.providers = LLMProviders() if LLMProviders else None

    def run(self):
        log.info("LIS Healer Daemon started. Watching for errors in lis_errors.log...")
        while True:
            try:
                self.check_logs()
            except Exception as e:
                log.error(f"Healer encountered an error: {e}")
            time.sleep(2)

    def check_logs(self):
        if not self.error_log.exists():
            return
            
        current_size = self.error_log.stat().st_size
        if current_size < self.last_position:
            # File was truncated/rotated
            self.last_position = 0
            
        if current_size == self.last_position:
            return
            
        with open(self.error_log, 'r', encoding='utf-8') as f:
            f.seek(self.last_position)
            for line in f:
                self.process_line(line)
            self.last_position = f.tell()
            
    def process_line(self, line: str):
        line = line.rstrip()
        
        # Start of a traceback?
        if "Traceback (most recent call last):" in line:
            self.in_traceback = True
            self.current_traceback = [line]
            return
            
        if self.in_traceback:
            if line.startswith(" ") or line.startswith("  ") or not line:
                # Continuation of traceback
                self.current_traceback.append(line)
            elif re.match(r'^[A-Za-z0-9_]+Error:', line) or re.match(r'^[A-Za-z0-9_]+Exception:', line):
                # The actual exception message (end of traceback)
                self.current_traceback.append(line)
                self.handle_error("\n".join(self.current_traceback))
                self.in_traceback = False
                self.current_traceback = []
            else:
                # Traceback ended abruptly
                self.handle_error("\n".join(self.current_traceback))
                self.in_traceback = False
                self.current_traceback = []
                
    def handle_error(self, tb_text: str):
        log.info("Detected application error/traceback!")
        log.info(tb_text)
        
        if not self.providers:
            log.error("LLMProviders not available. Cannot generate patch.")
            return

        # Extract files involved
        files = set(re.findall(r'File "([^"]+)"', tb_text))
        local_files = [f for f in files if f.lower().startswith(str(Path(__file__).parent).lower())]
        
        context = ""
        for filepath in local_files:
            try:
                p = Path(filepath)
                if p.exists():
                    context += f"\n--- {p.name} ---\n"
                    # Read the whole file for context
                    context += p.read_text(encoding='utf-8')
            except Exception:
                pass
                
        if not context:
            log.warning("Could not extract local source context for this error.")
            return
            
        log.info("Generating patch...")
        asyncio.run(self.generate_patch(tb_text, context))

    async def generate_patch(self, traceback_str: str, source_context: str):
        system_prompt = (
            "You are LIS's autonomous healing module. Your job is to read python tracebacks "
            "and the associated source code, and provide a unified diff (.patch) that fixes the issue. "
            "Output ONLY the raw diff text. No markdown formatting, no explanations, no wrapping backticks. "
            "Just the standard unified diff."
        )
        
        user_prompt = f"Traceback:\n{traceback_str}\n\nSource Code:\n{source_context}\n\nProvide the patch."
        messages = [{"role": "user", "content": user_prompt}]
        
        patch_content = await self.providers.generate(messages, system=system_prompt)
            
        if not patch_content:
            log.error("Could not generate patch (LLMs failed).")
            return
            
        # Clean up patch content if it has backticks
        patch_content = patch_content.replace("```diff", "").replace("```", "").strip()
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        patch_path = self.patches_dir / f"auto_heal_{timestamp}.patch"
        patch_path.write_text(patch_content, encoding="utf-8")
        log.info(f"✅ Created healing patch: {patch_path}")

if __name__ == "__main__":
    healer = HealerDaemon()
    healer.run()
