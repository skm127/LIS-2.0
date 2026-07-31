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

class SmartHomeSkill(Skill):
    name = "smart_home_control"
    description = "Control physical smart home devices like lights, locks, and thermostats. Accepts device/state or entity_id/action."

    async def execute(self, device: str = None, state: str = None, entity_id: str = None, action: str = None, **kwargs) -> SkillResult:
        actual_entity = entity_id or device
        actual_action = action or state

        if not actual_entity or not actual_action:
            return SkillResult(False, "Must provide either device/state or entity_id/action.")

        import os
        ha_url = os.environ.get("HA_URL")
        ha_token = os.environ.get("HA_TOKEN")
        
        if not ha_url or not ha_token:
            return SkillResult(True, f"Turned {actual_action} the {actual_entity}, sir. (Simulated, Home Assistant not configured)")
            
        try:
            import aiohttp
            
            headers = {
                "Authorization": f"Bearer {ha_token}",
                "Content-Type": "application/json",
            }
            
            if actual_action.lower() in ["on", "off"]:
                actual_action = f"turn_{actual_action.lower()}"
                
            if '.' not in actual_entity:
                actual_entity = f"light.{actual_entity.replace(' ', '_').lower()}"
                
            domain = actual_entity.split('.')[0]
            endpoint = f"{ha_url.rstrip('/')}/api/services/{domain}/{actual_action}"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(endpoint, headers=headers, json={"entity_id": actual_entity}) as resp:
                    if resp.status in [200, 201]:
                        return SkillResult(True, f"Successfully executed {actual_action} on {actual_entity}.")
                    else:
                        error_text = await resp.text()
                        return SkillResult(False, f"Home Assistant error ({resp.status}): {error_text}")
                        
        except ImportError:
            return SkillResult(False, "aiohttp is not installed. Run: pip install aiohttp")
        except Exception as e:
            return SkillResult(False, f"Failed to connect to Smart Home: {e}")
registry.register(SmartHomeSkill())

