import asyncio
import logging
import psutil
import time

log = logging.getLogger("lis.proactive")
logging.basicConfig(level=logging.INFO)

class ProactiveDaemon:
    def __init__(self, agent_spawner=None):
        self.running = False
        self.agent_spawner = agent_spawner
        self.last_alert_time = 0
        self.alert_cooldown = 3600  # 1 hour between identical alerts
        self._task = None

    async def start(self):
        if self.running: return
        self.running = True
        
        # Initialize CPU percent reference frame
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass
            
        self._task = asyncio.create_task(self._monitor_loop())
        log.info("LIS 4.0 Proactive Daemon started.")

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("LIS 4.0 Proactive Daemon stopped.")

    async def _monitor_loop(self):
        while self.running:
            try:
                # CPU and RAM checks
                # interval=None prevents blocking the async event loop!
                cpu_percent = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory()
                
                # Detect anomaly
                if cpu_percent > 95 or ram.percent > 95:
                    await self._handle_anomaly(f"High resource usage detected: CPU {cpu_percent}%, RAM {ram.percent}%")
                    
                # In the future: check calendar API, emails, or server pings
                
                await asyncio.sleep(60) # Check every minute
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Proactive Daemon error: {e}")
                await asyncio.sleep(60)

    async def _handle_anomaly(self, description: str):
        now = time.time()
        if now - self.last_alert_time < self.alert_cooldown:
            return # Don't spam
            
        self.last_alert_time = now
        log.warning(f"PROACTIVE ALERT: {description}")
        
        if self.agent_spawner:
            log.info("Spawning agent to investigate anomaly...")
            # Spawn a background agent to analyze the situation
            task_str = f"System anomaly detected: {description}. Please analyze the current running processes and provide a diagnostic report."
            
            async def _run_agent():
                try:
                    await self.agent_spawner(task_str)
                except Exception as e:
                    log.error(f"Anomaly agent failed: {e}")
            
            # Fire and forget safely
            asyncio.create_task(_run_agent())
