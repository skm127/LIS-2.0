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

class MCPActionSkill(Skill):
    name = "mcp_call"
    description = "Execute a tool on an external MCP (Model Context Protocol) server."

    async def execute(self, server_name: str, tool_name: str, arguments: str = "{}", **kwargs) -> SkillResult:
        try:
            import json
            from mcp_client import mcp_manager
            
            args_dict = json.loads(arguments) if isinstance(arguments, str) else arguments
            
            client = mcp_manager.clients.get(server_name)
            if not client:
                return SkillResult(False, f"MCP Server '{server_name}' is not configured.")
                
            result = await client.call_tool(tool_name, args_dict)
            if result.get("success"):
                return SkillResult(True, f"Successfully executed {tool_name} on {server_name}.", data=result.get("data"))
            else:
                return SkillResult(False, f"MCP execution failed: {result.get('error')}")
                
        except Exception as e:
            return SkillResult(False, f"MCP call error: {e}")


# Omniscience (Phase 1)
registry.register(MCPActionSkill())

class SubAgentSkill(Skill):
    name = "spawn_agent"
    description = "Spawn a specialized sub-agent to handle a long-running or complex background task. Returns the final summary from the agent."

    async def execute(self, task_description: str, **kwargs) -> SkillResult:
        if not registry.agent_spawner:
            return SkillResult(False, "Agent spawner is not configured in the registry.")
            
        try:
            log.info(f"Spawning sub-agent for task: {task_description}")
            # Call the injected spawner
            result = await registry.agent_spawner(task_description)
            return SkillResult(True, f"Sub-agent completed the task. Result: {result}")
        except Exception as e:
            return SkillResult(False, f"Sub-agent failed: {e}")


# Smart Home IoT (Phase 4)
registry.register(SubAgentSkill())

