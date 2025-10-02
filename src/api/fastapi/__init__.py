from fastapi import APIRouter, FastAPI
from .routes import register_routes


class FastAPIApp:
    def __init__(self, lifespan=None):
        self.app = FastAPI(lifespan=lifespan)
        self.__register_routes()

    def get_app(self):
        return self.app
    
    def __register_routes(self):
        api_router = APIRouter(prefix="/api")
        register_routes(api_router)
        self.app.include_router(api_router)
        