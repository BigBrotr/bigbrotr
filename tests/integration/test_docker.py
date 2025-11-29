"""
Docker Integration Tests for BigBrotr.

These tests verify the Docker deployment configuration files exist and are valid.
The actual Docker build/run tests require Docker daemon to be running.

Run with: pytest tests/integration/ -v
"""

from pathlib import Path

import pytest

COMPOSE_DIR = Path(__file__).parent.parent.parent / "implementations" / "bigbrotr"


class TestDockerComposeConfig:
    """Test Docker Compose configuration files exist and are valid."""

    def test_compose_file_exists(self):
        """docker-compose.yaml should exist."""
        assert (COMPOSE_DIR / "docker-compose.yaml").exists()

    def test_dockerfile_exists(self):
        """Dockerfile should exist."""
        assert (COMPOSE_DIR / "Dockerfile").exists()

    def test_env_example_exists(self):
        """.env.example should exist."""
        assert (COMPOSE_DIR / ".env.example").exists()


class TestPostgresConfig:
    """Test PostgreSQL configuration files."""

    def test_postgresql_conf_exists(self):
        """postgresql.conf should exist."""
        assert (COMPOSE_DIR / "postgres" / "postgresql.conf").exists()

    def test_postgresql_conf_not_empty(self):
        """postgresql.conf should not be empty."""
        conf_file = COMPOSE_DIR / "postgres" / "postgresql.conf"
        assert conf_file.stat().st_size > 100  # Should have substantial content

    def test_sql_init_files_exist(self):
        """All SQL init files should exist."""
        init_dir = COMPOSE_DIR / "postgres" / "init"

        expected_files = [
            "00_extensions.sql",
            "01_utility_functions.sql",
            "02_tables.sql",
            "03_indexes.sql",
            "04_integrity_functions.sql",
            "05_procedures.sql",
            "06_views.sql",
            "99_verify.sql",
        ]

        for filename in expected_files:
            assert (init_dir / filename).exists(), f"Missing SQL file: {filename}"

    def test_sql_files_not_empty(self):
        """SQL init files should not be empty."""
        init_dir = COMPOSE_DIR / "postgres" / "init"

        for sql_file in init_dir.glob("*.sql"):
            size = sql_file.stat().st_size
            assert size > 0, f"{sql_file.name} is empty"


class TestPGBouncerConfig:
    """Test PGBouncer configuration files."""

    def test_pgbouncer_ini_exists(self):
        """pgbouncer.ini should exist."""
        assert (COMPOSE_DIR / "pgbouncer" / "pgbouncer.ini").exists()

    def test_pgbouncer_userlist_template_exists(self):
        """userlist.txt.template should exist."""
        assert (COMPOSE_DIR / "pgbouncer" / "userlist.txt.template").exists()

    def test_pgbouncer_ini_has_transaction_mode(self):
        """pgbouncer.ini should use transaction mode for asyncpg compatibility."""
        ini_file = COMPOSE_DIR / "pgbouncer" / "pgbouncer.ini"
        content = ini_file.read_text()
        assert "pool_mode = transaction" in content


class TestYAMLConfigs:
    """Test YAML configuration files."""

    def test_brotr_yaml_exists(self):
        """brotr.yaml should exist."""
        assert (COMPOSE_DIR / "yaml" / "core" / "brotr.yaml").exists()

    def test_brotr_docker_yaml_exists(self):
        """brotr.docker.yaml should exist."""
        assert (COMPOSE_DIR / "yaml" / "core" / "brotr.docker.yaml").exists()

    def test_brotr_pgbouncer_yaml_exists(self):
        """brotr.pgbouncer.yaml should exist."""
        assert (COMPOSE_DIR / "yaml" / "core" / "brotr.pgbouncer.yaml").exists()

    def test_initializer_yaml_exists(self):
        """initializer.yaml should exist."""
        assert (COMPOSE_DIR / "yaml" / "services" / "initializer.yaml").exists()

    def test_finder_yaml_exists(self):
        """finder.yaml should exist."""
        assert (COMPOSE_DIR / "yaml" / "services" / "finder.yaml").exists()

    def test_brotr_docker_has_postgres_host(self):
        """brotr.docker.yaml should use 'postgres' as host."""
        yaml_file = COMPOSE_DIR / "yaml" / "core" / "brotr.docker.yaml"
        content = yaml_file.read_text()
        assert "host: postgres" in content

    def test_brotr_pgbouncer_has_pgbouncer_host(self):
        """brotr.pgbouncer.yaml should use 'pgbouncer' as host."""
        yaml_file = COMPOSE_DIR / "yaml" / "core" / "brotr.pgbouncer.yaml"
        content = yaml_file.read_text()
        assert "host: pgbouncer" in content
        assert "port: 6432" in content


class TestDockerfileContent:
    """Test Dockerfile content."""

    def test_dockerfile_uses_python_311(self):
        """Dockerfile should use Python 3.11."""
        dockerfile = COMPOSE_DIR / "Dockerfile"
        content = dockerfile.read_text()
        assert "python:3.11" in content

    def test_dockerfile_has_nonroot_user(self):
        """Dockerfile should create non-root user for security."""
        dockerfile = COMPOSE_DIR / "Dockerfile"
        content = dockerfile.read_text()
        assert "useradd" in content or "adduser" in content

    def test_dockerfile_sets_pythonpath(self):
        """Dockerfile should set PYTHONPATH."""
        dockerfile = COMPOSE_DIR / "Dockerfile"
        content = dockerfile.read_text()
        assert "PYTHONPATH" in content


class TestDockerComposeContent:
    """Test docker-compose.yaml content."""

    def test_compose_has_postgres_service(self):
        """docker-compose.yaml should define postgres service."""
        compose = COMPOSE_DIR / "docker-compose.yaml"
        content = compose.read_text()
        assert "postgres:" in content

    def test_compose_has_initializer_service(self):
        """docker-compose.yaml should define initializer service."""
        compose = COMPOSE_DIR / "docker-compose.yaml"
        content = compose.read_text()
        assert "initializer:" in content

    def test_compose_has_finder_service(self):
        """docker-compose.yaml should define finder service."""
        compose = COMPOSE_DIR / "docker-compose.yaml"
        content = compose.read_text()
        assert "finder:" in content

    def test_compose_uses_postgresql_conf(self):
        """docker-compose.yaml should mount postgresql.conf."""
        compose = COMPOSE_DIR / "docker-compose.yaml"
        content = compose.read_text()
        assert "postgresql.conf" in content

    def test_compose_initializer_depends_on_postgres(self):
        """Initializer should depend on postgres being healthy."""
        compose = COMPOSE_DIR / "docker-compose.yaml"
        content = compose.read_text()
        assert "service_healthy" in content

    def test_compose_finder_depends_on_initializer(self):
        """Finder should depend on initializer completing."""
        compose = COMPOSE_DIR / "docker-compose.yaml"
        content = compose.read_text()
        assert "service_completed_successfully" in content

    def test_compose_services_use_docker_flag(self):
        """Services should use --docker flag."""
        compose = COMPOSE_DIR / "docker-compose.yaml"
        content = compose.read_text()
        assert '"--docker"' in content
