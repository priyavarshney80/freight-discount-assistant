# Freight Discount Assistant

An AI assistant that answers seller questions about freight discount eligibility,
platform policy, and cross-seller ranking, using a combination of structured data
(Excel), business rule logic, RAG over policy documents, and a locally hosted LLM
(via LM Studio).

Live Demo: https://freight-discount-assistant.onrender.com

## Folder structure

```
freight-discount-assistant/
├── backend/
│   ├── business_rules.py      Eligibility + discount calculation
│   ├── analytics.py            Cross-seller ranking logic
│   ├── time_utils.py           Resolves "last 3 months", "2026", etc. from query text
│   ├── rag_engine.py           Chunking, indexing, and retrieval of policy documents
│   ├── llm_orchestrator.py     Decides intent, calls the right tool, generates the answer
│   └── main.py                 FastAPI server (API + serves the frontend)
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── script.js
├── data/
│   ├── seller_master.xlsx      Seller ID <-> Seller Name mapping
│   ├── orders_data.xlsx        Order-level data with status per order
│   └── policy_docs/
│       └── general_policy.txt  The written policy RAG is grounded in
├── uploaded_docs/               Seller-specific agreements land here when uploaded
├── test_scenarios.py
└── requirements.txt
```

## One-time setup

1. Create and activate a virtual environment:
   ```
   python3 -m venv venv
   source venv/bin/activate
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Start LM Studio, load a model, and click "Start Server" so it is running at
   `http://localhost:1234/v1`. If your LM Studio shows a different model name,
   update `MODEL_NAME` in `backend/llm_orchestrator.py`.

## Running the test scenarios (no browser needed)

```
python3 test_scenarios.py
```

## Running the full app

```
cd backend
uvicorn main:app --reload
```

Then open your browser at:
```
http://localhost:8000
```

The first time it runs, `rag_engine.py` will download a small embedding model
from the internet automatically — this needs an internet connection once, after
that it works fully offline against your local LM Studio.

## Notes on the data

- `orders_data.xlsx` is order-level (one row per order) so eligibility can be
  calculated correctly: only orders with status "Fulfilled" count towards the
  100-order threshold. Cancelled, Failed Delivery, and Returned orders do not count.
- Myntra has 100+ fulfilled orders in August 2026 in the sample data, so it is the
  one seller that shows a non-zero discount out of the box — useful for testing
  the eligible path.
- Uploading a PDF/text agreement in the sidebar and tagging it to a specific
  seller means that seller's policy questions will retrieve from both the
  general policy and their specific agreement; other sellers are unaffected.
