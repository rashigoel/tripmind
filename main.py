"""TripMind v2 — entry point."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from server.api import app, PORT

if __name__ == "__main__":
    uvicorn.run("server.api:app", host="0.0.0.0", port=PORT, reload=False)
