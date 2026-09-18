"""Run ``python -m src.runpod_api`` inside the GPU Pod."""

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "src.runpod_api.app:create_app",
        host="0.0.0.0",
        port=int(os.getenv("AI_API_PORT", "8000")),
        workers=1,
        factory=True,
    )
