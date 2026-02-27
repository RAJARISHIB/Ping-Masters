from fastapi import FastAPI
import uvicorn


app = FastAPI(title="Ping Masters API")


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "Ping Masters API is running"}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
