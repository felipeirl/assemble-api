from fastapi import FastAPI

app = FastAPI(title="Assemble Backend")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
