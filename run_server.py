"""Arranque local: `uv run python run_server.py`. En Cloud Run arranca el CMD del Dockerfile."""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("src.main:app", host="127.0.0.1", port=int(os.getenv("PORT", "8080")), workers=1)
