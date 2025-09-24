from fastapi import FastAPI
from . import health, user

def register_routes(app: FastAPI):
    app.include_router(health.router)
    app.include_router(user.router)
