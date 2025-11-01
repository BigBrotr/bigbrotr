"""Brotr Implementation Registry - Plugin System for Extensibility.

This module provides automatic discovery and registration of Brotr implementations.
Any developer can create a new Brotr by simply adding a folder with the required structure.

Architecture:
    - BrotrRegistry: Discovers and registers all Brotr implementations
    - Auto-discovery: Scans implementation directories
    - Convention over configuration: Standard folder structure
    - Pluggable: Add new implementations without changing core code

How to Create a New Brotr Implementation:
    1. Create folder: implementations/<your_brotr>/
    2. Add: sql/init.sql (database schema)
    3. Add: repositories/event_repository.py (storage strategy)
    4. Add: config.yaml (optional configuration)
    5. Deploy: The system automatically detects and registers it!

Example Structure:
    implementations/
    ├── bigbrotr/
    │   ├── sql/init.sql
    │   └── repositories/event_repository.py
    ├── lilbrotr/
    │   ├── sql/init.sql
    │   └── repositories/event_repository.py
    └── mediumbrotr/              # NEW! Just add this folder
        ├── sql/init.sql
        └── repositories/event_repository.py

Dependencies:
    - importlib: Dynamic module loading
    - pathlib: File system operations
    - base_event_repository: Abstract base for implementations
"""
import os
import sys
import importlib.util
import logging
from pathlib import Path
from typing import Dict, Type, Optional, List
from abc import ABC

from brotr_core.database.base_event_repository import BaseEventRepository

__all__ = ['BrotrRegistry', 'register_implementation', 'get_implementation', 'list_implementations']


class BrotrRegistry:
    """Registry for Brotr implementations with automatic discovery.
    
    This class scans the implementations directory and automatically registers
    all valid Brotr implementations, making the system truly extensible.
    
    Attributes:
        implementations (Dict[str, Type[BaseEventRepository]]): Registered implementations
        implementations_dir (Path): Directory containing implementations
    """
    
    _instance = None
    _implementations: Dict[str, Type[BaseEventRepository]] = {}
    _implementations_dir: Optional[Path] = None
    
    def __new__(cls):
        """Singleton pattern - only one registry instance."""
        if cls._instance is None:
            cls._instance = super(BrotrRegistry, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize registry if not already initialized."""
        if not self._initialized:
            self._initialized = True
            self._discover_implementations()
    
    def _discover_implementations(self):
        """Automatically discover all Brotr implementations.
        
        Scans the implementations directory and registers any valid
        Brotr implementation found.
        """
        # Find implementations directory
        project_root = Path(__file__).parent.parent
        self._implementations_dir = project_root / "implementations"
        
        # Create implementations directory if it doesn't exist
        if not self._implementations_dir.exists():
            self._implementations_dir.mkdir(parents=True, exist_ok=True)
            logging.info(f"📁 Created implementations directory: {self._implementations_dir}")
            return
        
        # Scan for implementations (exclude template and hidden directories)
        for impl_dir in self._implementations_dir.iterdir():
            if impl_dir.is_dir() and not impl_dir.name.startswith('.') and impl_dir.name != '_template':
                self._register_implementation_from_dir(impl_dir)
        
        logging.info(f"✅ Discovered {len(self._implementations)} Brotr implementations: {list(self._implementations.keys())}")
    
    def _register_implementation_from_dir(self, impl_dir: Path):
        """Register a Brotr implementation from a directory.
        
        Args:
            impl_dir: Directory containing the implementation
            
        Expected Structure:
            implementations/<name>/
            ├── sql/init.sql              (required)
            ├── repositories/
            │   └── event_repository.py   (required)
            └── config.yaml               (optional)
        """
        impl_name = impl_dir.name.lower()
        
        # Check for required files
        sql_file = impl_dir / "sql" / "init.sql"
        repo_file = impl_dir / "repositories" / "event_repository.py"
        
        if not sql_file.exists():
            logging.warning(f"⚠️ Skipping {impl_name}: missing sql/init.sql")
            return
        
        if not repo_file.exists():
            logging.warning(f"⚠️ Skipping {impl_name}: missing repositories/event_repository.py")
            return
        
        # Try to load the event repository class
        try:
            repo_class = self._load_event_repository(impl_name, repo_file)
            if repo_class:
                self._implementations[impl_name] = repo_class
                logging.info(f"✅ Registered implementation: {impl_name}")
        except Exception as e:
            logging.error(f"❌ Failed to register {impl_name}: {e}")
    
    def _load_event_repository(self, impl_name: str, repo_file: Path) -> Optional[Type[BaseEventRepository]]:
        """Dynamically load event repository class from file.
        
        Args:
            impl_name: Name of the implementation
            repo_file: Path to event_repository.py file
            
        Returns:
            Event repository class or None if not found
            
        Raises:
            ImportError: If module cannot be loaded
            AttributeError: If EventRepository class not found
        """
        # Create module name
        module_name = f"implementations.{impl_name}.repositories.event_repository"
        
        # Load module dynamically
        spec = importlib.util.spec_from_file_location(module_name, repo_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {repo_file}")
        
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        
        # Find EventRepository class
        if not hasattr(module, 'EventRepository'):
            raise AttributeError(f"Module {module_name} must define 'EventRepository' class")
        
        repo_class = getattr(module, 'EventRepository')
        
        # Verify it extends BaseEventRepository
        if not issubclass(repo_class, BaseEventRepository):
            raise TypeError(f"EventRepository in {module_name} must extend BaseEventRepository")
        
        return repo_class
    
    def register(self, name: str, repository_class: Type[BaseEventRepository]):
        """Manually register a Brotr implementation.
        
        Args:
            name: Implementation name (e.g., 'bigbrotr', 'lilbrotr')
            repository_class: Event repository class
            
        Raises:
            TypeError: If repository_class doesn't extend BaseEventRepository
            ValueError: If name already registered
        """
        if not issubclass(repository_class, BaseEventRepository):
            raise TypeError(f"{repository_class} must extend BaseEventRepository")
        
        if name.lower() in self._implementations:
            raise ValueError(f"Implementation '{name}' already registered")
        
        self._implementations[name.lower()] = repository_class
        logging.info(f"✅ Manually registered implementation: {name}")
    
    def get(self, name: str) -> Optional[Type[BaseEventRepository]]:
        """Get registered implementation by name.
        
        Args:
            name: Implementation name (case-insensitive)
            
        Returns:
            Event repository class or None if not found
        """
        return self._implementations.get(name.lower())
    
    def list(self) -> List[str]:
        """List all registered implementation names.
        
        Returns:
            List of implementation names
        """
        return list(self._implementations.keys())
    
    def get_sql_path(self, name: str) -> Optional[Path]:
        """Get path to SQL init file for implementation.
        
        Args:
            name: Implementation name
            
        Returns:
            Path to init.sql or None if not found
        """
        if self._implementations_dir is None:
            return None
        
        impl_dir = self._implementations_dir / name.lower()
        sql_file = impl_dir / "sql" / "init.sql"
        
        return sql_file if sql_file.exists() else None
    
    def exists(self, name: str) -> bool:
        """Check if implementation is registered.
        
        Args:
            name: Implementation name
            
        Returns:
            True if registered, False otherwise
        """
        return name.lower() in self._implementations


# Global registry instance
_registry = BrotrRegistry()


# Convenience functions
def register_implementation(name: str, repository_class: Type[BaseEventRepository]):
    """Register a Brotr implementation.
    
    Args:
        name: Implementation name
        repository_class: Event repository class
    """
    _registry.register(name, repository_class)


def get_implementation(name: str) -> Optional[Type[BaseEventRepository]]:
    """Get a registered Brotr implementation.
    
    Args:
        name: Implementation name
        
    Returns:
        Event repository class or None
    """
    return _registry.get(name)


def list_implementations() -> List[str]:
    """List all registered Brotr implementations.
    
    Returns:
        List of implementation names
    """
    return _registry.list()


def get_sql_path(name: str) -> Optional[Path]:
    """Get SQL init path for implementation.
    
    Args:
        name: Implementation name
        
    Returns:
        Path to init.sql or None
    """
    return _registry.get_sql_path(name)


def implementation_exists(name: str) -> bool:
    """Check if implementation exists.
    
    Args:
        name: Implementation name
        
    Returns:
        True if exists, False otherwise
    """
    return _registry.exists(name)

