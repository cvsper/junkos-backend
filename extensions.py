"""
Shared Flask extension instances.

Created as a separate module to avoid circular imports when route
blueprints need access to extensions that are initialised in server.py.
"""

import os

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Use Redis for rate-limit storage when available (production), otherwise
# fall back to in-memory storage (single-process / development).
_storage_uri = os.environ.get("REDIS_URL") or "memory://"

# Limiter is created without an app; init_app() is called in server.py.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_storage_uri,
    default_limits=["100 per minute"],
)
