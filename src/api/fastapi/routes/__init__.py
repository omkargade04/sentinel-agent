from fastapi import FastAPI
from . import health

def register_routes(app: FastAPI):
    app.include_router(health.router)
