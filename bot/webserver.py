from fastapi import FastAPI
import uvicorn
import os
import threading

app = FastAPI()

@app.get("/")
async def home():
    return {
        "status": "alive",
        "service": "Velocity Bingo Bot"
    }

@app.get("/health")
async def health():
    return {"ok": True}

def run():
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")

def start_webserver():
    threading.Thread(target=run, daemon=True).start()
