from fastapi import FastAPI


class FastAPIApp:
    def __init__(self):
        self.app = FastAPI()

    def get_app(self):
        return self.app