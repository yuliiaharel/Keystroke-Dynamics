"""App creation and wiring."""

from fastapi import FastAPI

app = FastAPI(title="Keystroke Dynamics")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
