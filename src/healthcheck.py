"""Simple HTTP health check server for monitoring service status."""
import logging
from aiohttp import web
from typing import Callable, Awaitable


class HealthCheckServer:
    """Lightweight HTTP server for health checks.

    Provides /health and /ready endpoints for Kubernetes/Docker health probes.
    """

    def __init__(self, port: int = 8080, ready_check: Callable[[], Awaitable[bool]] = None):
        """Initialize health check server.

        Args:
            port: Port to listen on
            ready_check: Optional async function that returns True when service is ready
        """
        self.port = port
        self.ready_check = ready_check
        self.app = web.Application()
        self.runner = None
        self.site = None

        # Setup routes
        self.app.router.add_get('/health', self.health_handler)
        self.app.router.add_get('/ready', self.ready_handler)
        self.app.router.add_get('/', self.root_handler)

    async def health_handler(self, request: web.Request) -> web.Response:
        """Liveness probe - returns 200 if process is running."""
        return web.Response(text='OK', status=200)

    async def ready_handler(self, request: web.Request) -> web.Response:
        """Readiness probe - returns 200 if service is ready to accept traffic."""
        if self.ready_check:
            try:
                is_ready = await self.ready_check()
                if is_ready:
                    return web.Response(text='READY', status=200)
                else:
                    return web.Response(text='NOT READY', status=503)
            except Exception as e:
                logging.warning(f"⚠️ Readiness check failed: {e}")
                return web.Response(text=f'ERROR: {e}', status=503)
        else:
            # No readiness check configured, assume ready if healthy
            return web.Response(text='READY', status=200)

    async def root_handler(self, request: web.Request) -> web.Response:
        """Root handler - provides service info."""
        return web.Response(text='BigBrotr Health Check Server\n/health - liveness\n/ready - readiness', status=200)

    async def start(self):
        """Start the health check server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '0.0.0.0', self.port)
        await self.site.start()
        logging.info(f"✅ Health check server listening on port {self.port}")

    async def stop(self):
        """Stop the health check server."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        logging.info("✅ Health check server stopped")
