# Backward-compat shim — use app.db.session directly in new code
from app.db.session import (  # noqa: F401
    close_engine as close_pool,
    get_session_factory,
    init_engine as init_pool,
)
