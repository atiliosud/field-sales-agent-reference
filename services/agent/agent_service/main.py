from fastapi import FastAPI

app = FastAPI(title="agent-service")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
