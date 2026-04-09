from fastapi import FastAPI
from analyse import analyse

app = FastAPI()

@app.get("/api/analyse")
def run_analysis(sym: str):
    return analyse(sym)
