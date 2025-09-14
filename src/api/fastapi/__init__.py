from fastapi import FastAPI
from .routes import register_routes


class FastAPIApp:
    def __init__(self):
        self.app = FastAPI()
        self.__register_routes()

    def get_app(self):
        return self.app
    
    def __register_routes(self):
        register_routes(self.app)
        