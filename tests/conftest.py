"""pytest configuration for the orthofinder-explorer test suite.

Flask and Flask-SQLAlchemy are not available in the lightweight test
environment.  The models module (app/models.py) has no Flask dependency of
its own, but importing the ``app`` package triggers ``app/__init__.py`` which
imports Flask at module level.

This conftest stubs out Flask and Flask-SQLAlchemy *before* any test module
imports from ``app``, allowing the pure-SQLAlchemy model definitions and the
ingestion scripts to be tested without a full Flask installation.
"""

import sys
from unittest.mock import MagicMock

# Stub Flask and Flask-SQLAlchemy if they are not installed.
for mod in ("flask", "flask_sqlalchemy"):
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            sys.modules[mod] = MagicMock()
            # flask_sqlalchemy.SQLAlchemy must be a class-like callable
            if mod == "flask_sqlalchemy":
                sys.modules[mod].SQLAlchemy = MagicMock
