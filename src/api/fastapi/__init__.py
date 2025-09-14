from fastapi import FastAPI


class FastAPIApp:
    def __init__(self):
        self.app = FastAPI()
        self.__register_health_check()
        self.__register_ping()

    def get_app(self):
        return self.app
    
    def __register_health_check(self):
        @self.app.get("/health")
        def health_check():
            return {"status": "ok"}
    
    def __register_ping(self):
        @self.app.get("/ping")
        def ping():
            return {"status": "pong"}
        