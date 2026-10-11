import os
import shutil
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from llm_orchestrator import handle_query_with_meta, reset_session
from rag_engine import index_uploaded_document, load_and_index_policies
from business_rules import load_seller_master, add_seller

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploaded_docs")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="Freight Discount Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    query: str
    role: str = "seller"
    session_id: str = "default"


class ResetRequest(BaseModel):
    session_id: str = "default"


class AddSellerRequest(BaseModel):
    name: str


@app.on_event("startup")
def startup_event():
    load_and_index_policies()


@app.get("/api/sellers")
def get_sellers():
    df = load_seller_master()
    return df.to_dict(orient="records")


@app.post("/api/sellers")
def create_seller(payload: AddSellerRequest):
    seller_id, seller_name, created = add_seller(payload.name)
    return {"seller_id": seller_id, "seller_name": seller_name, "created": created}


@app.post("/api/ask")
def ask(payload: AskRequest):
    result = handle_query_with_meta(payload.query, user_role=payload.role, session_id=payload.session_id)
    return result


@app.post("/api/reset")
def reset(payload: ResetRequest):
    reset_session(payload.session_id)
    return {"status": "reset"}


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...), seller_id: str = Form(default=None)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    chunks_indexed = index_uploaded_document(file_path, seller_id=seller_id)

    return {
        "status": "success",
        "filename": file.filename,
        "seller_tag": seller_id if seller_id else "general",
        "chunks_indexed": chunks_indexed
    }


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")