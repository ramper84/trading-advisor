from fastapi import FastAPI

from app.routers import health

app = FastAPI(title="Trading Advisor")

app.include_router(health.router)
