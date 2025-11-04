"""Centralized configuration management for all BigBrotr services."""
import os
import re
import sys
import json
import logging
import time
from typing import Dict, Any
from multiprocessing import cpu_count
from nostr_tools import validate_keypair


def load_monitor_config() -> Dict[str, Any]:
    """Load monitor service configuration from environment variables."""
    try:
        config: Dict[str, Any] = {
            "database_host": str(os.environ["POSTGRES_HOST"]),
            "database_user": str(os.environ["POSTGRES_USER"]),
            "database_password": str(os.environ["POSTGRES_PASSWORD"]),
            "database_name": str(os.environ["POSTGRES_DB"]),
            "database_port": int(os.environ["POSTGRES_PORT"]),
            "torproxy_host": str(os.environ["TORPROXY_HOST"]),
            "torproxy_port": int(os.environ["TORPROXY_PORT"]),
            "frequency_hour": int(os.environ["MONITOR_FREQUENCY_HOUR"]),
            "num_cores": int(os.environ["MONITOR_NUM_CORES"]),
            "chunk_size": int(os.environ["MONITOR_CHUNK_SIZE"]),
            "requests_per_core": int(os.environ["MONITOR_REQUESTS_PER_CORE"]),
            "timeout": int(os.environ["MONITOR_REQUEST_TIMEOUT"]),
            "secret_key": str(os.environ["SECRET_KEY"]),
            "public_key": str(os.environ["PUBLIC_KEY"]),
            "loop_interval_minutes": int(os.environ.get("MONITOR_LOOP_INTERVAL_MINUTES", "15"))
        }

        # Validation
        _validate_port(config["database_port"], "POSTGRES_PORT")
        _validate_port(config["torproxy_port"], "TORPROXY_PORT")
        _validate_positive(config["frequency_hour"], "MONITOR_FREQUENCY_HOUR")
        _validate_positive(config["num_cores"], "MONITOR_NUM_CORES")
        _validate_positive(config["chunk_size"], "MONITOR_CHUNK_SIZE")
        _validate_positive(config["requests_per_core"], "MONITOR_REQUESTS_PER_CORE")
        _validate_positive(config["timeout"], "MONITOR_REQUEST_TIMEOUT")
        _validate_positive(config["loop_interval_minutes"], "MONITOR_LOOP_INTERVAL_MINUTES")

        if not validate_keypair(config["secret_key"], config["public_key"]):
            logging.error("❌ Invalid SECRET_KEY or PUBLIC_KEY.")
            sys.exit(1)

        if config["num_cores"] > cpu_count():
            logging.warning(f"⚠️ MONITOR_NUM_CORES exceeds available CPU cores ({cpu_count()}).")
            config["num_cores"] = cpu_count()
            logging.info(f"🔄 MONITOR_NUM_CORES set to {config['num_cores']} (max available).")

    except KeyError as e:
        logging.error(f"❌ Missing environment variable: {e}")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"❌ Invalid environment variable value: {e}")
        sys.exit(1)

    return config


def load_synchronizer_config() -> Dict[str, Any]:
    """Load synchronizer service configuration from environment variables."""
    try:
        config: Dict[str, Any] = {
            "database_host": str(os.environ["POSTGRES_HOST"]),
            "database_user": str(os.environ["POSTGRES_USER"]),
            "database_password": str(os.environ["POSTGRES_PASSWORD"]),
            "database_name": str(os.environ["POSTGRES_DB"]),
            "database_port": int(os.environ["POSTGRES_PORT"]),
            "torproxy_host": str(os.environ["TORPROXY_HOST"]),
            "torproxy_port": int(os.environ["TORPROXY_PORT"]),
            "num_cores": int(os.environ["SYNCHRONIZER_NUM_CORES"]),
            "requests_per_core": int(os.environ["SYNCHRONIZER_REQUESTS_PER_CORE"]),
            "timeout": int(os.environ["SYNCHRONIZER_REQUEST_TIMEOUT"]),
            "start_timestamp": int(os.environ["SYNCHRONIZER_START_TIMESTAMP"]),
            "stop_timestamp": int(os.environ["SYNCHRONIZER_STOP_TIMESTAMP"]),
            "event_filter": json.loads(os.environ["SYNCHRONIZER_EVENT_FILTER"]),
            "priority_relays_path": str(os.environ.get("SYNCHRONIZER_PRIORITY_RELAYS_PATH")),
            "relay_metadata_threshold_hours": int(os.environ.get("SYNCHRONIZER_RELAY_METADATA_THRESHOLD_HOURS", "12")),
            "loop_interval_minutes": int(os.environ.get("SYNCHRONIZER_LOOP_INTERVAL_MINUTES", "15")),
            "batch_size": int(os.environ.get("SYNCHRONIZER_BATCH_SIZE", "500"))
        }

        # Validation
        _validate_port(config["database_port"], "POSTGRES_PORT")
        _validate_port(config["torproxy_port"], "TORPROXY_PORT")
        _validate_positive(config["num_cores"], "SYNCHRONIZER_NUM_CORES")
        _validate_positive(config["requests_per_core"], "SYNCHRONIZER_REQUESTS_PER_CORE")
        _validate_positive(config["timeout"], "SYNCHRONIZER_REQUEST_TIMEOUT")
        _validate_positive(config["relay_metadata_threshold_hours"], "SYNCHRONIZER_RELAY_METADATA_THRESHOLD_HOURS")
        _validate_positive(config["loop_interval_minutes"], "SYNCHRONIZER_LOOP_INTERVAL_MINUTES")
        _validate_positive(config["batch_size"], "SYNCHRONIZER_BATCH_SIZE")

        if config["start_timestamp"] < 0:
            logging.error("❌ Invalid SYNCHRONIZER_START_TIMESTAMP. Must be 0 or greater.")
            sys.exit(1)

        if config["stop_timestamp"] != -1 and config["stop_timestamp"] < 0:
            logging.error("❌ Invalid SYNCHRONIZER_STOP_TIMESTAMP. Must be -1, 0, or greater.")
            sys.exit(1)

        if config["stop_timestamp"] != -1 and config["start_timestamp"] > config["stop_timestamp"]:
            logging.error("❌ SYNCHRONIZER_START_TIMESTAMP cannot be greater than SYNCHRONIZER_STOP_TIMESTAMP.")
            sys.exit(1)

        # Warn about future timestamps
        current_time = int(time.time())
        if config["start_timestamp"] > current_time:
            logging.warning(f"⚠️ SYNCHRONIZER_START_TIMESTAMP ({config['start_timestamp']}) is in the future")
        if config["stop_timestamp"] != -1 and config["stop_timestamp"] > current_time:
            logging.warning(f"⚠️ SYNCHRONIZER_STOP_TIMESTAMP ({config['stop_timestamp']}) is in the future")

        if not isinstance(config["event_filter"], dict):
            logging.error("❌ SYNCHRONIZER_EVENT_FILTER must be a valid JSON object.")
            sys.exit(1)

        # Filter only valid Nostr filter keys (NIP-01: single lowercase letter tags)
        config["event_filter"] = {
            k: v for k, v in config["event_filter"].items()
            if k in {"ids", "authors", "kinds"} or re.fullmatch(r"#[a-z]", k)
        }

        if config["num_cores"] > cpu_count():
            logging.warning(f"⚠️ SYNCHRONIZER_NUM_CORES exceeds available CPU cores ({cpu_count()}).")
            config["num_cores"] = cpu_count()
            logging.info(f"🔄 SYNCHRONIZER_NUM_CORES set to {config['num_cores']} (max available).")

        # Validate priority relays file exists, create if missing
        if config["priority_relays_path"]:
            if not os.path.exists(config["priority_relays_path"]):
                logging.warning(f"⚠️ Priority relays file not found: {config['priority_relays_path']}")
                logging.info("📝 Creating empty priority relays file...")
                try:
                    with open(config["priority_relays_path"], 'w', encoding='utf-8') as f:
                        f.write("# Priority relays (one URL per line)\n")
                        f.write("# Example:\n")
                        f.write("# wss://relay.example.com\n")
                    logging.info(f"✅ Created {config['priority_relays_path']}")
                except IOError as e:
                    logging.error(f"❌ Failed to create priority relays file: {e}")
                    sys.exit(1)

    except KeyError as e:
        logging.error(f"❌ Missing environment variable: {e}")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"❌ Invalid environment variable value: {e}")
        sys.exit(1)

    return config


def load_initializer_config() -> Dict[str, Any]:
    """Load initializer service configuration from environment variables."""
    try:
        config: Dict[str, Any] = {
            "database_host": str(os.environ["POSTGRES_HOST"]),
            "database_user": str(os.environ["POSTGRES_USER"]),
            "database_password": str(os.environ["POSTGRES_PASSWORD"]),
            "database_name": str(os.environ["POSTGRES_DB"]),
            "database_port": int(os.environ["POSTGRES_PORT"]),
            "seed_relays_path": str(os.environ["SEED_RELAYS_PATH"])
        }

        # Validation
        _validate_port(config["database_port"], "POSTGRES_PORT")

        if not os.path.exists(config["seed_relays_path"]):
            logging.error(f"❌ SEED_RELAYS_PATH file not found: {config['seed_relays_path']}")
            sys.exit(1)

    except KeyError as e:
        logging.error(f"❌ Missing environment variable: {e}")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"❌ Invalid environment variable value: {e}")
        sys.exit(1)

    return config


def load_finder_config() -> Dict[str, Any]:
    """Load finder service configuration from environment variables."""
    try:
        config: Dict[str, Any] = {
            "database_host": str(os.environ["POSTGRES_HOST"]),
            "database_user": str(os.environ["POSTGRES_USER"]),
            "database_password": str(os.environ["POSTGRES_PASSWORD"]),
            "database_name": str(os.environ["POSTGRES_DB"]),
            "database_port": int(os.environ["POSTGRES_PORT"]),
            "torproxy_host": str(os.environ["TORPROXY_HOST"]),
            "torproxy_port": int(os.environ["TORPROXY_PORT"]),
            "frequency_hour": int(os.environ["FINDER_FREQUENCY_HOUR"]),
            "timeout": int(os.environ["FINDER_REQUEST_TIMEOUT"])
        }

        # Validation
        _validate_port(config["database_port"], "POSTGRES_PORT")
        _validate_port(config["torproxy_port"], "TORPROXY_PORT")
        _validate_positive(config["frequency_hour"], "FINDER_FREQUENCY_HOUR")
        _validate_positive(config["timeout"], "FINDER_REQUEST_TIMEOUT")

    except KeyError as e:
        logging.error(f"❌ Missing environment variable: {e}")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"❌ Invalid environment variable value: {e}")
        sys.exit(1)

    return config


# --- Helper Validation Functions ---

def _validate_port(port: int, name: str) -> None:
    """Validate port is in valid range."""
    if port < 0 or port > 65535:
        logging.error(f"❌ Invalid {name}. Must be between 0 and 65535.")
        sys.exit(1)


def _validate_positive(value: int, name: str) -> None:
    """Validate value is positive."""
    if value < 1:
        logging.error(f"❌ Invalid {name}. Must be at least 1.")
        sys.exit(1)
