import logging
import os
import sys

import uvicorn
import yaml
from dotenv import load_dotenv


def load_config() -> dict:
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    api_key = os.getenv("QWEN_API_KEY", "")
    config.setdefault("api", {})["api_key"] = api_key
    return config


def main():
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = load_config()

    if not config.get("api", {}).get("api_key"):
        print(
            "\nERROR: QWEN_API_KEY is not set.\n"
            "  1. Copy .env.example to .env\n"
            "  2. Add your DashScope API key\n"
            "  3. Re-run the app\n"
        )
        sys.exit(1)

    from app.server import create_app

    app = create_app(config)
    server_cfg = config.get("server", {})
    port = server_cfg.get("port", 8000)

    print(f"\n  ProWatch AI is running →  http://localhost:{port}\n")

    uvicorn.run(app, host=server_cfg.get("host", "0.0.0.0"), port=port, log_level="warning")


if __name__ == "__main__":
    main()
