"""
SME Research Assistant - Service Health Check Utility

Validates connectivity to all critical services before pipeline startup.
"""
import logging
import httpx
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class HealthCheckResult:
    """Result of a health check operation."""

    def __init__(self, service: str, status: str, message: str, details: Optional[Dict] = None):
        self.service = service
        self.status = status  # "pass", "warn", "fail"
        self.message = message
        self.details = details or {}

    def is_healthy(self) -> bool:
        return self.status == "pass"

    def __repr__(self):
        symbol = "✓" if self.status == "pass" else "⚠" if self.status == "warn" else "✗"
        return f"{symbol} [{self.service.upper()}] {self.message}"


class HealthChecker:
    """Performs startup health checks on critical services."""

    def __init__(self, timeout: int = 5):
        """
        Args:
            timeout: Connection timeout in seconds (default: 5)
        """
        self.timeout = timeout
        self.results: List[HealthCheckResult] = []

    def check_all(
        self,
        qdrant_url: str,
        ollama_url: str,
        redis_host: str,
        redis_port: int,
        db_path: str
    ) -> List[HealthCheckResult]:
        """
        Run all health checks.

        Args:
            qdrant_url: Qdrant service URL (e.g., http://sme_qdrant:6333)
            ollama_url: Ollama service URL (e.g., http://sme_ollama:11434)
            redis_host: Redis hostname (e.g., sme_redis)
            redis_port: Redis port (default: 6379)
            db_path: Path to SQLite database file

        Returns:
            List of HealthCheckResult objects
        """
        self.results = []

        # Check services in dependency order
        self.check_database(db_path)
        self.check_qdrant(qdrant_url)
        self.check_ollama(ollama_url)
        self.check_redis(redis_host, redis_port)

        return self.results

    def check_database(self, db_path: str) -> HealthCheckResult:
        """Check if SQLite database file exists and is accessible."""
        try:
            path = Path(db_path)

            if not path.exists():
                result = HealthCheckResult(
                    service="database",
                    status="warn",
                    message=f"Database file does not exist (will be created): {db_path}",
                    details={"path": str(path)}
                )
            elif not path.is_file():
                result = HealthCheckResult(
                    service="database",
                    status="fail",
                    message=f"Database path exists but is not a file: {db_path}",
                    details={"path": str(path)}
                )
            else:
                # Try to open it
                import sqlite3
                conn = sqlite3.connect(str(path), timeout=2)
                conn.close()

                result = HealthCheckResult(
                    service="database",
                    status="pass",
                    message=f"Database accessible at {db_path}",
                    details={"path": str(path), "size_mb": path.stat().st_size / (1024 * 1024)}
                )

        except Exception as e:
            result = HealthCheckResult(
                service="database",
                status="fail",
                message=f"Database check failed: {e}",
                details={"error": str(e)}
            )

        self.results.append(result)
        logger.info(result)
        return result

    def check_qdrant(self, qdrant_url: str) -> HealthCheckResult:
        """Check if Qdrant vector store is accessible."""
        try:
            # Normalize URL
            if not qdrant_url.startswith("http"):
                qdrant_url = f"http://{qdrant_url}"

            # Try health endpoint
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{qdrant_url}/health")

                if response.status_code == 200:
                    result = HealthCheckResult(
                        service="qdrant",
                        status="pass",
                        message=f"Qdrant responding at {qdrant_url}",
                        details={"url": qdrant_url, "status_code": 200}
                    )
                else:
                    result = HealthCheckResult(
                        service="qdrant",
                        status="warn",
                        message=f"Qdrant responded with status {response.status_code}",
                        details={"url": qdrant_url, "status_code": response.status_code}
                    )

        except httpx.ConnectError as e:
            result = HealthCheckResult(
                service="qdrant",
                status="fail",
                message=f"Cannot connect to Qdrant at {qdrant_url}",
                details={"url": qdrant_url, "error": str(e)}
            )
        except httpx.TimeoutException:
            result = HealthCheckResult(
                service="qdrant",
                status="fail",
                message=f"Qdrant connection timeout at {qdrant_url}",
                details={"url": qdrant_url, "timeout": self.timeout}
            )
        except Exception as e:
            result = HealthCheckResult(
                service="qdrant",
                status="fail",
                message=f"Qdrant check failed: {e}",
                details={"url": qdrant_url, "error": str(e)}
            )

        self.results.append(result)
        logger.info(result)
        return result

    def check_ollama(self, ollama_url: str) -> HealthCheckResult:
        """Check if Ollama service is accessible."""
        try:
            # Normalize URL
            if not ollama_url.startswith("http"):
                ollama_url = f"http://{ollama_url}"

            # Try /api/tags endpoint
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{ollama_url}/api/tags")

                if response.status_code == 200:
                    data = response.json()
                    models = data.get("models", [])
                    model_names = [m.get("name", "unknown") for m in models]

                    result = HealthCheckResult(
                        service="ollama",
                        status="pass",
                        message=f"Ollama responding at {ollama_url} ({len(models)} models available)",
                        details={"url": ollama_url, "models": model_names}
                    )
                else:
                    result = HealthCheckResult(
                        service="ollama",
                        status="warn",
                        message=f"Ollama responded with status {response.status_code}",
                        details={"url": ollama_url, "status_code": response.status_code}
                    )

        except httpx.ConnectError as e:
            result = HealthCheckResult(
                service="ollama",
                status="fail",
                message=f"Cannot connect to Ollama at {ollama_url}",
                details={"url": ollama_url, "error": str(e)}
            )
        except httpx.TimeoutException:
            result = HealthCheckResult(
                service="ollama",
                status="fail",
                message=f"Ollama connection timeout at {ollama_url}",
                details={"url": ollama_url, "timeout": self.timeout}
            )
        except Exception as e:
            result = HealthCheckResult(
                service="ollama",
                status="warn",
                message=f"Ollama check failed (may still work): {e}",
                details={"url": ollama_url, "error": str(e)}
            )

        self.results.append(result)
        logger.info(result)
        return result

    def check_redis(self, redis_host: str, redis_port: int) -> HealthCheckResult:
        """Check if Redis cache is accessible."""
        try:
            import redis

            # Try to connect and ping
            client = redis.Redis(
                host=redis_host,
                port=redis_port,
                socket_connect_timeout=self.timeout,
                socket_timeout=self.timeout
            )

            response = client.ping()

            if response:
                result = HealthCheckResult(
                    service="redis",
                    status="pass",
                    message=f"Redis responding at {redis_host}:{redis_port}",
                    details={"host": redis_host, "port": redis_port}
                )
            else:
                result = HealthCheckResult(
                    service="redis",
                    status="warn",
                    message=f"Redis did not respond to PING",
                    details={"host": redis_host, "port": redis_port}
                )

        except redis.exceptions.ConnectionError as e:
            result = HealthCheckResult(
                service="redis",
                status="warn",
                message=f"Cannot connect to Redis (cache disabled): {e}",
                details={"host": redis_host, "port": redis_port, "error": str(e)}
            )
        except redis.exceptions.TimeoutError:
            result = HealthCheckResult(
                service="redis",
                status="warn",
                message=f"Redis connection timeout (cache disabled)",
                details={"host": redis_host, "port": redis_port, "timeout": self.timeout}
            )
        except ImportError:
            result = HealthCheckResult(
                service="redis",
                status="warn",
                message="Redis library not installed (cache disabled)",
                details={"host": redis_host, "port": redis_port}
            )
        except Exception as e:
            result = HealthCheckResult(
                service="redis",
                status="warn",
                message=f"Redis check failed (cache disabled): {e}",
                details={"host": redis_host, "port": redis_port, "error": str(e)}
            )

        self.results.append(result)
        logger.info(result)
        return result

    def has_critical_failures(self) -> bool:
        """Check if any critical services failed (Qdrant, Database)."""
        critical_services = {"qdrant", "database"}

        for result in self.results:
            if result.service in critical_services and result.status == "fail":
                return True
        return False

    def get_summary(self) -> str:
        """Get a human-readable summary of all checks."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == "pass")
        warned = sum(1 for r in self.results if r.status == "warn")
        failed = sum(1 for r in self.results if r.status == "fail")

        lines = [
            "=" * 60,
            "  SERVICE HEALTH CHECK SUMMARY",
            "=" * 60,
        ]

        for result in self.results:
            lines.append(str(result))

        lines.append("")
        lines.append(f"Total: {total} | Passed: {passed} | Warnings: {warned} | Failed: {failed}")

        if self.has_critical_failures():
            lines.append("")
            lines.append("❌ CRITICAL SERVICES FAILED - Pipeline cannot start")
            lines.append("   Please check service connectivity and configuration")
        elif failed > 0:
            lines.append("")
            lines.append("⚠️  Some services failed but pipeline can continue")
        elif warned > 0:
            lines.append("")
            lines.append("⚠️  All critical services healthy (some warnings)")
        else:
            lines.append("")
            lines.append("✅ All services healthy!")

        lines.append("=" * 60)

        return "\n".join(lines)
