"""
LIS 2.0 - Model Context Protocol (MCP) Client
Implements a true JSON-RPC 2.0 over stdio transport layer.
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any, List

log = logging.getLogger("LIS.mcp")

class MCPClient:
    """
    A true Model Context Protocol (MCP) Client over stdio.
    """
    
    def __init__(self, server_config: Dict[str, Any]):
        self.config = server_config
        self.connected = False
        self._process: Optional[asyncio.subprocess.Process] = None
        self._tools_cache: List[Dict] = []
        self._msg_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._read_task: Optional[asyncio.Task] = None
        
    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def connect(self) -> bool:
        """Establish stdio connection and perform MCP initialization handshake."""
        if self.connected: return True
        
        try:
            cmd = self.config.get("command")
            args = self.config.get("args", [])
            
            if not cmd:
                log.error("MCP config missing 'command'")
                return False
                
            log.info(f"Spawning MCP Server: {cmd} {' '.join(args)}")
            
            # Spawn the subprocess
            self._process = await asyncio.create_subprocess_exec(
                cmd, *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # On Windows, creationflags may be needed to hide console, but default is fine
            )
            
            # Start the read loop
            self._read_task = asyncio.create_task(self._read_loop())
            
            # Step 1: Send Initialize Request
            init_id = self._next_id()
            init_req = {
                "jsonrpc": "2.0",
                "id": init_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {
                        "name": "LIS",
                        "version": "2.0"
                    },
                    "capabilities": {}
                }
            }
            
            future = asyncio.get_event_loop().create_future()
            self._pending_requests[init_id] = future
            
            await self._send(init_req)
            
            # Wait for initialize response
            init_resp = await asyncio.wait_for(future, timeout=10.0)
            if "error" in init_resp:
                log.error(f"MCP Initialize failed: {init_resp['error']}")
                return False
                
            # Step 2: Send notifications/initialized
            initialized_req = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            }
            await self._send(initialized_req)
            
            self.connected = True
            log.info("MCP Server fully initialized.")
            
            # Auto-fetch tools on connect
            await self.list_tools()
            
            return True
            
        except Exception as e:
            log.error(f"Failed to connect to MCP Server: {e}")
            await self.disconnect()
            return False

    async def _send(self, message: Dict):
        """Send JSON-RPC message over stdin."""
        if not self._process or not self._process.stdin:
            raise ConnectionError("Process stdin is closed.")
        msg_str = json.dumps(message) + "\n"
        self._process.stdin.write(msg_str.encode('utf-8'))
        await self._process.stdin.drain()

    async def _read_loop(self):
        """Read JSON-RPC messages from stdout."""
        if not self._process or not self._process.stdout:
            return
            
        while True:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break # EOF
                    
                line_str = line.decode('utf-8').strip()
                if not line_str: continue
                
                try:
                    msg = json.loads(line_str)
                except json.JSONDecodeError:
                    log.debug(f"MCP non-JSON output: {line_str}")
                    continue
                    
                msg_id = msg.get("id")
                
                # Handle Responses
                if msg_id is not None and msg_id in self._pending_requests:
                    future = self._pending_requests.pop(msg_id)
                    if not future.done():
                        future.set_result(msg)
                # Ignore notifications/logging from server for now
                
            except Exception as e:
                log.error(f"MCP read loop error: {e}")
                break
                
        self.connected = False
        log.warning("MCP Server stdout closed. Disconnected.")

    async def _send_rpc(self, method: str, params: Dict = None) -> Dict:
        """Send a request and wait for the response."""
        if not self.connected:
            if not await self.connect():
                return {"error": {"message": "Failed to connect to MCP server"}}
                
        msg_id = self._next_id()
        req = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method
        }
        if params is not None:
            req["params"] = params
            
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[msg_id] = future
        
        await self._send(req)
        
        try:
            resp = await asyncio.wait_for(future, timeout=30.0)
            return resp
        except asyncio.TimeoutError:
            self._pending_requests.pop(msg_id, None)
            return {"error": {"message": "MCP request timed out"}}

    async def list_tools(self) -> List[Dict]:
        """Fetch available tools from the MCP server."""
        resp = await self._send_rpc("tools/list")
        if "error" in resp:
            log.error(f"Failed to list tools: {resp['error']}")
            return []
            
        tools = resp.get("result", {}).get("tools", [])
        self._tools_cache = tools
        return tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool on the remote MCP Server."""
        log.info(f"Calling MCP tool '{tool_name}' with args: {arguments}")
        
        resp = await self._send_rpc("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })
        
        if "error" in resp:
            return {"success": False, "error": resp["error"].get("message", "Unknown error")}
            
        result = resp.get("result", {})
        
        # Format MCP content block result
        content_blocks = result.get("content", [])
        text_output = ""
        for block in content_blocks:
            if block.get("type") == "text":
                text_output += block.get("text", "") + "\n"
                
        if result.get("isError"):
            return {"success": False, "error": text_output.strip()}
            
        return {
            "success": True, 
            "result": "Success",
            "data": text_output.strip()
        }
        
    async def disconnect(self):
        """Cleanly shutdown the MCP Server connection."""
        self.connected = False
        if self._read_task:
            self._read_task.cancel()
        if self._process:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass
            self._process = None
        log.info("Disconnected from MCP Server.")

# Global instance for managing multiple servers
class MCPManager:
    def __init__(self):
        self.clients: Dict[str, MCPClient] = {}
        
    def add_server(self, name: str, config: Dict[str, Any]):
        self.clients[name] = MCPClient(config)
        
    async def get_all_tools(self) -> Dict[str, List[Dict]]:
        tools = {}
        for name, client in self.clients.items():
            tools[name] = await client.list_tools()
        return tools

# Singleton manager
mcp_manager = MCPManager()

# Default servers (Will be overridden by .env config in the future)
# Example: Using the npx package to launch the SQLite server
# mcp_manager.add_server("sqlite", {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-sqlite", "test.db"]})
