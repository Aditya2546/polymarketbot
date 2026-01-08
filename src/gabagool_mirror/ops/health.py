"""
Health Server - HTTP endpoints for health checks and metrics.
"""

import asyncio
import json
from datetime import datetime
from typing import Callable, Dict, Optional
from aiohttp import web
import logging

from .metrics import get_metrics

logger = logging.getLogger(__name__)


class HealthServer:
    """
    HTTP server for health checks and metrics.
    
    Endpoints:
    - GET /health - Health check
    - GET /ready - Readiness check
    - GET /metrics - Prometheus metrics
    - GET /status - Detailed status JSON
    """
    
    def __init__(
        self,
        port: int = 8080,
        metrics_port: Optional[int] = None
    ):
        """
        Initialize health server.
        
        Args:
            port: HTTP port for health/status endpoints
            metrics_port: Optional separate port for metrics
        """
        self.port = port
        self.metrics_port = metrics_port
        
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        
        self._health_checks: Dict[str, Callable] = {}
        self._status_provider: Optional[Callable] = None
        
        self._start_time = datetime.utcnow()
        self._healthy = True
        self._ready = False
    
    def register_health_check(self, name: str, check: Callable) -> None:
        """
        Register a health check function.
        
        Args:
            name: Check name
            check: Async function returning (healthy: bool, message: str)
        """
        self._health_checks[name] = check
    
    def set_status_provider(self, provider: Callable) -> None:
        """
        Set the status provider function.
        
        Args:
            provider: Async function returning status dict
        """
        self._status_provider = provider
    
    def set_ready(self, ready: bool) -> None:
        """Set readiness state."""
        self._ready = ready
    
    async def _health_handler(self, request: web.Request) -> web.Response:
        """Handle health check requests."""
        checks = {}
        all_healthy = True
        
        for name, check in self._health_checks.items():
            try:
                healthy, message = await check()
                checks[name] = {"healthy": healthy, "message": message}
                if not healthy:
                    all_healthy = False
            except Exception as e:
                checks[name] = {"healthy": False, "message": str(e)}
                all_healthy = False
        
        uptime = (datetime.utcnow() - self._start_time).total_seconds()
        
        response = {
            "status": "healthy" if all_healthy else "unhealthy",
            "uptime_seconds": uptime,
            "checks": checks
        }
        
        status_code = 200 if all_healthy else 503
        return web.json_response(response, status=status_code)
    
    async def _ready_handler(self, request: web.Request) -> web.Response:
        """Handle readiness check requests."""
        if self._ready:
            return web.json_response({"ready": True})
        return web.json_response({"ready": False}, status=503)
    
    async def _metrics_handler(self, request: web.Request) -> web.Response:
        """Handle metrics requests."""
        metrics = get_metrics()
        return web.Response(
            text=metrics.get_metrics_text(),
            content_type="text/plain"
        )
    
    async def _status_handler(self, request: web.Request) -> web.Response:
        """Handle detailed status requests."""
        status = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "uptime_seconds": (datetime.utcnow() - self._start_time).total_seconds(),
            "healthy": self._healthy,
            "ready": self._ready,
        }
        
        if self._status_provider:
            try:
                detailed = await self._status_provider()
                status.update(detailed)
            except Exception as e:
                status["status_error"] = str(e)
        
        return web.json_response(status)
    
    async def start(self) -> None:
        """Start the health server."""
        self._app = web.Application()
        
        self._app.router.add_get("/health", self._health_handler)
        self._app.router.add_get("/ready", self._ready_handler)
        self._app.router.add_get("/metrics", self._metrics_handler)
        self._app.router.add_get("/status", self._status_handler)
        
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        
        self._site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await self._site.start()
        
        logger.info(f"Health server started on port {self.port}")
    
    async def stop(self) -> None:
        """Stop the health server."""
        if self._runner:
            await self._runner.cleanup()
            logger.info("Health server stopped")

