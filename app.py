import sys
import os

# add api folder to path
sys.path.append(os.path.join(os.path.dirname(__file__), "api"))

from fastapi import FastAPI
from analyse import analyse

app = FastAPI()

@app.get("/api/analyse")
def run_analysis(sym: str):
    return analyse(sym)
