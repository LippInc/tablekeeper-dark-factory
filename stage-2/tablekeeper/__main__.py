"""Serve the API on 0.0.0.0:$PORT (default 8080) in one process (§3.1)."""
import os

import uvicorn

from .http import create_app

uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")),
            workers=1, access_log=False)
