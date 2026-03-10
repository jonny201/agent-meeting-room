from __future__ import annotations

import os
import sys


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(CURRENT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from agent_meeting_room.webapp import create_app


def main() -> None:
    app = create_app()
    host = os.getenv("AMR_HOST", "0.0.0.0")
    port = int(os.getenv("AMR_PORT", "8000"))
    debug = os.getenv("AMR_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()