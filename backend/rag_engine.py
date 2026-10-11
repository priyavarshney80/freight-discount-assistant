import os
import chromadb
from pypdf import PdfReader

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY_DIR = os.path.join(BASE_DIR, "data", "policy_docs")
CHROMA_DIR = os.path.join(BASE_DIR, "chroma_store")

client = chromadb.PersistentClient(path=CHROMA_DIR)
collection = client.get_or_create_collection(name="policy_documents")

CHUNK_SIZE = 200
CHUNK_OVERLAP = 40


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    words = text.split()
    if not words:
        return []
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk.strip())
        if end >= len(words):
            break
        start += chunk_size - overlap
    return chunks


def extract_text_from_pdf(filepath):
    reader = PdfReader(filepath)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text


def extract_text_from_file(filepath):
    if filepath.lower().endswith(".pdf"):
        return extract_text_from_pdf(filepath)
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def load_and_index_policies():
    if not os.path.exists(POLICY_DIR):
        return
    for filename in os.listdir(POLICY_DIR):
        if filename.endswith(".txt"):
            filepath = os.path.join(POLICY_DIR, filename)
            text = extract_text_from_file(filepath)
            chunks = chunk_text(text)
            for i, chunk in enumerate(chunks):
                doc_id = f"general_{filename}_{i}"
                collection.upsert(
                    documents=[chunk],
                    metadatas=[{"source": filename, "seller_tag": "general"}],
                    ids=[doc_id]
                )
    print(f"Indexed general policy documents from {POLICY_DIR}")


def index_uploaded_document(filepath, seller_id=None):
    text = extract_text_from_file(filepath)
    chunks = chunk_text(text)
    tag = seller_id if seller_id else "general"
    filename = os.path.basename(filepath)

    for i, chunk in enumerate(chunks):
        doc_id = f"{tag}_{filename}_{i}"
        collection.upsert(
            documents=[chunk],
            metadatas=[{"source": filename, "seller_tag": tag}],
            ids=[doc_id]
        )
    return len(chunks)


def retrieve_relevant_policy(query, seller_id=None, n_results=3):
    if seller_id:
        where_filter = {"seller_tag": {"$in": ["general", seller_id]}}
        results = collection.query(query_texts=[query], n_results=n_results, where=where_filter)
    else:
        results = collection.query(query_texts=[query], n_results=n_results)

    return results["documents"][0] if results["documents"] else []


def get_seller_specific_document(seller_id):
    if not seller_id:
        return []
    results = collection.get(where={"seller_tag": seller_id})
    return results["documents"] if results and results.get("documents") else []


if __name__ == "__main__":
    load_and_index_policies()
    print(retrieve_relevant_policy("does a cancelled order count as fulfilled"))