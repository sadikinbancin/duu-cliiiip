from __future__ import annotations

import os

from app import demo


def get_auth():
    """Return optional Gradio basic-auth credentials from HF Space secrets."""
    username = os.getenv("APP_USERNAME", "").strip()
    password = os.getenv("APP_PASSWORD", "")

    if bool(username) != bool(password):
        raise RuntimeError(
            "APP_USERNAME and APP_PASSWORD must both be configured in Hugging Face Space Secrets."
        )

    if username and password:
        return (username, password)
    return None


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1, max_size=8)
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        auth=get_auth(),
        auth_message="Private KiinStudio Media clipping workspace",
        enable_monitoring=False,
    )
