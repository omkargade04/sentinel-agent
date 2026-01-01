from fastapi import FastAPI
from . import health, user, github, repository, indexing

def register_routes(app: FastAPI):
    app.include_router(health.router)
    app.include_router(user.router)
    app.include_router(github.router)
    app.include_router(repository.router)
    app.include_router(indexing.router)
