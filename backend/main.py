import os
import re
import time

import fitz
import numpy as np
from google import genai
from google.genai import types
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client

from app.text_chunker import chunk_text


load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is missing from backend/.env"
    )

gemini_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(
        timeout=30000,
        retry_options=types.HttpRetryOptions(attempts=1),
    ),
)

GEMINI_MODEL = "gemini-2.5-flash"
EMBEDDING_MODEL = "gemini-embedding-001"

def generate_embeddings(texts, task_type):
    try:
        embeddings = []

        for text in texts:
            result = gemini_client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=text,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=384,
                ),
            )

            embeddings.append(result.embeddings[0].values)

        embeddings = np.asarray(embeddings, dtype=np.float32)

        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / np.maximum(norms, 1e-12)

        return embeddings

    except Exception as exc:
        print(f"Embedding API error: {exc}")
        raise HTTPException(
            status_code=502,
            detail="Could not generate text embeddings. Please try again.",
        ) from exc

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    raise RuntimeError(
        "Set SUPABASE_URL and SUPABASE_SECRET_KEY in backend/.env"
    )

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)

app = FastAPI(
    title="ResearchMate AI",
    description="AI-powered research assistant",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=10)


@app.get("/")
def root():
    return {
        "message": "ResearchMate AI backend is running!"
    }


@app.get("/health")
def health():
    return {"status": "healthy"}



@app.post("/upload-paper")
async def upload_paper(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Please upload a PDF file."
        )

    contents = await file.read()

    if len(contents) > 15 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="The PDF must be smaller than 15 MB."
        )

    # 1. Extract text while the PDF is open.
    try:
        with fitz.open(stream=contents, filetype="pdf") as document:
            page_count = len(document)

            page_texts = [
                (page_number, page.get_text().strip())
                for page_number, page in enumerate(document, start=1)
                if page.get_text().strip()
            ]

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Could not read this PDF."
        ) from exc

    if not page_texts:
        raise HTTPException(
            status_code=422,
            detail="No selectable text found in the PDF. OCR may be required."
        )

    full_text = "\n\n".join(
        f"--- Page {page_number} ---\n{text}"
        for page_number, text in page_texts
    )

    # 2. Chunk each page separately and preserve its page number.
    chunks = []
    chunk_page_numbers = []

    for page_number, page_text in page_texts:
        page_chunks = chunk_text(
            page_text,
            chunk_size=1500,
            overlap=200
        )

        for chunk in page_chunks:
            if chunk.strip():
                chunks.append(chunk)
                chunk_page_numbers.append(page_number)

    if not chunks:
        raise HTTPException(
            status_code=422,
            detail="Could not create text chunks from this PDF."
        )

    # 3. Generate embeddings.
    embeddings = generate_embeddings(
    chunks, task_type="RETRIEVAL_DOCUMENT"
)
    # 4. Prepare database records.
    records = []

    for index, chunk in enumerate(chunks):
        records.append({
            "filename": file.filename,
            "chunk_index": index,
            "page_number": chunk_page_numbers[index],
            "chunk_text": chunk,
            "embedding": np.asarray(
                embeddings[index],
                dtype=float
            ).tolist()
        })

    # 5. Replace existing chunks for this filename.
    try:
        supabase.table("paper_chunks").delete().eq(
            "filename", file.filename
        ).execute()

        # Insert records in batches.
        for start in range(0, len(records), 50):
            supabase.table("paper_chunks").insert(
                records[start:start + 50]
            ).execute()

    except Exception as exc:
        print(f"Supabase upload error: {exc}")
        raise HTTPException(
            status_code=500,
            detail=(
                "Could not save the paper to Supabase. "
                "Check your table, vector extension, and credentials."
            )
        ) from exc

    return {
        "success": True,
        "filename": file.filename,
        "pages": page_count,
        "characters": len(full_text),
        "total_chunks": len(chunks),
        "embedding_dimensions": int(embeddings.shape[1]),
        "message": "Paper and embeddings saved to Supabase."
    }


@app.post("/search-paper")
def search_paper(request: SearchRequest):
    query_embedding = generate_embeddings(
        [request.query], task_type="RETRIEVAL_QUERY"
    )[0]
    try:
        response = supabase.rpc(
            "match_paper_chunks",
            {
                "query_embedding": query_embedding.tolist(),
                "match_count": request.top_k
            }
        ).execute()

        results = response.data or []

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Semantic search failed. Check the database function."
        ) from exc

    return {
        "query": request.query,
        "results": results
    }
    
    
    
    

class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=10)


@app.post("/ask")

def ask_research_question(request: AskRequest):
    # 1. Embed the question.
    total_start = time.perf_counter()
    start_time = time.perf_counter()
    query_embedding = generate_embeddings(
        [request.question], task_type="RETRIEVAL_QUERY"
    )[0]    
    print(f"Embedding time: {time.perf_counter() - start_time:.2f}s")
    # 2. Retrieve relevant passages from Supabase.
    search_start = time.perf_counter()
    try:
        response = supabase.rpc(
            "match_paper_chunks",
            {
                "query_embedding": query_embedding.tolist(),
                "match_count": request.top_k
            }
        ).execute()

        passages = response.data or []
        print(f"Supabase search time: {time.perf_counter() - search_start:.2f}s")

    except Exception as exc:
        print(f"Supabase retrieval error: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve research passages."
        ) from exc

    if not passages:
        raise HTTPException(
            status_code=404,
            detail="No research passages found. Upload a paper first."
        )

    # 3. Build the context and source list.
    context_parts = []
    sources = []

    for i, passage in enumerate(passages, start=1):
        source_id = f"S{i}"
        filename = passage.get("filename", "Unknown paper")
        page = passage.get("page_number")
        chunk_text_value = passage.get("chunk_text", "")

        sources.append({
            "id": source_id,
            "filename": filename,
            "page": page,
            "chunk_id": passage.get("chunk_index"),
            "similarity": passage.get("similarity"),
            "passage": chunk_text_value
        })

        context_parts.append(
            f"[{source_id}]\n"
            f"Paper: {filename}\n"
            f"Page: {page if page is not None else 'Unknown'}\n"
            f"Passage:\n{chunk_text_value}"
        )

    context = "\n\n---\n\n".join(context_parts)

    # 4. Prepare the Gemini prompt.
    prompt = f"""
You are ResearchMate AI, an intelligent research assistant that helps users understand academic papers.

Use the retrieved passages as the primary source of information.

Instructions:
1. Answer the user's question directly and provide a clear, detailed explanation.
2. Use relevant information from the passages, combining multiple passages when helpful.
3. Do not merely rephrase the question or repeat that the paper does not provide a formal definition.
4. If the paper discusses the topic indirectly, explain what can reasonably be concluded and distinguish it from explicitly stated information.
5. If the passages do not contain enough information to answer fully, clearly identify what is missing.
6. You may provide general background knowledge to clarify a concept when necessary, but label it as "General background—not explicitly explained in the paper."
7. Never invent paper-specific claims, results, statistics, or citations.
8. Cite claims based on retrieved passages using their source labels, such as [S1] and [S2].
9. Use clear, student-friendly language and explain technical terms when appropriate.
Do not give incomplete, one-line answers when the user asks
for a detailed explanation.

Explain the concept, its mechanism, and its relevance to the
paper using the available evidence.

Combine information from multiple relevant passages when
necessary. If the paper only briefly mentions a mechanism,
state that limitation instead of inventing missing details.

Clearly distinguish information explicitly stated in the paper
from general background knowledge.
Answer in 3–5 short paragraphs with headings when useful.

For technical questions, explain:
1. The concept or mechanism.
2. How it works step by step.
3. Its role in the paper, using supporting passages.
4. What the paper does not explain, if anything.

Do not stop after an introductory sentence.
Aim for 200–350 words when the available evidence supports it.
Never invent paper-specific details to meet the word target.
Write a complete, coherent answer that directly addresses every
part of the question.

For technical questions, explain the concept, mechanism, and
relevance to the paper when the retrieved evidence supports them.

Do not stop after an introductory sentence. If the paper does not
provide enough detail, state what is missing rather than inventing
information.

Use citations such as [S1] and [S2] for claims supported by the
retrieved passages.
STRICT SOURCE-GROUNDING RULES

1. Every claim about the paper must be supported by the cited passage.
2. Do not turn a potential benefit into a proven result.
3. Do not claim expert-level accuracy, clinical validation, or improved patient outcomes unless the retrieved passages explicitly establish it.
4. Clearly label general background knowledge as such.
5. Use citations immediately after the claims they support.
6. If evidence is insufficient, state that clearly instead of filling gaps with assumptions.
7. Distinguish between what the paper states, what can reasonably be inferred, and what remains unspecified.

EVIDENCE AND CITATION VALIDATION

- Do not exaggerate claims from the paper.
- Do not describe a proposed benefit as a proven outcome.
- Do not claim clinical validation or expert-level accuracy
  unless the retrieved evidence explicitly supports it.
- Never use a citation merely because a passage mentions the
  same topic. It must support the specific claim.
- If a retrieved passage contains broken or unclear wording,
  do not copy it as a technical definition.
- Separate your response into:
  1. What the paper explicitly states
  2. What can reasonably be inferred
  3. What the paper does not specify
- General background knowledge must be labelled clearly.
Answer every part of the user's question completely. Break multi-part questions into sub-questions and address each one explicitly. Use the retrieved source material as the primary evidence, include citations for factual claims, and identify contradictions or missing information in the source. Never stop after a brief introduction when the question requires a detailed explanation. If the retrieved context is insufficient, state what information is missing rather than inventing it.
Retrieved passages:
{context}

Question: {request.question}

Provide a useful answer with enough detail to help the user understand the topic.
"""

    # 5. Generate an answer, retrying temporary failures.
    gemini_start = time.perf_counter()
    answer = None

    for attempt in range(2):
        try:
            response = gemini_client.models.generate_content(
    model=GEMINI_MODEL,
    contents=prompt,
    config={
        "max_output_tokens": 2000,
        "temperature": 0.2,
    },
)

            
            answer = response.text or ""

            finish_reason = (
    response.candidates[0].finish_reason
    if response.candidates
    else "No candidates"
)

            print(f"Answer length: {len(answer)} characters")
            print(f"Finish reason: {finish_reason}")
            print(f"Gemini time: {time.perf_counter() - gemini_start:.2f}s")


            if not answer:
                raise HTTPException(
                    status_code=502,
                    detail="Gemini returned an empty answer. Please try again."
                )

            break

        except HTTPException:
            raise

        except Exception as exc:
            print(f"Gemini attempt {attempt + 1} failed: {exc}")

            error_text = str(exc).lower()
            is_temporary = any(
                term in error_text
                for term in (
                    "503",
                    "unavailable",
                    "429",
                    "resource_exhausted",
                    "500",
                    "high demand",
                    "overloaded"
                )
            )

            if not is_temporary or attempt == 2:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Gemini could not generate an answer. "
                        "Check the backend terminal."
                    )
                ) from exc

            # Retry at most once after a short delay.
            if not is_temporary or attempt == 1:
              raise HTTPException(
                status_code=502,
                detail="Gemini could not generate an answer. "
                "Check the backend terminal."
                ) from exc
            time.sleep(1)
            print("Retrying Gemini request...")
              
            print(
                f"Total /ask time: "
                f"{time.perf_counter() - total_start:.2f}s"
)
    # 6. Return the answer and source passages.
    return {
        "question": request.question,
        "answer": answer,
        "sources": sources
    }
