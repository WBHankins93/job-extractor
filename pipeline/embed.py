"""
pipeline/embed.py
-----------------
Stage 4 & 5: Embeddings + ChromaDB vector store + resume matching.

Concept: Embeddings
-------------------
An embedding converts text into a vector (a list of ~384 numbers).
The position of that vector in mathematical space represents its *meaning*.
Two texts with similar meaning → vectors close together in space.
Two texts with different meaning → vectors far apart.

We use this to answer: "How similar is this job description to my resume?"
That's cosine similarity — the angle between two vectors. Range: 0 to 1.
Closer to 1 = more similar.

Concept: Vector store (ChromaDB)
---------------------------------
A database optimized for storing and searching vectors.
Instead of WHERE name = 'foo', you query by similarity:
"give me the 5 vectors most similar to this query vector."
ChromaDB runs locally, persists to disk, and is the standard for
learning RAG architecture.
"""

from pathlib import Path
from fastembed import TextEmbedding
from pypdf import PdfReader
import chromadb
from chromadb.config import Settings


# -------------------------------------------------------------------
# Resume → Role mapping
#
# This is intentional design: instead of one generic resume,
# we surface the *most relevant* resume for each role type.
# -------------------------------------------------------------------

RESUME_DIR = Path("resume")

ROLE_TO_RESUME = {
    "Full Stack Engineer":        "Ben_Hankins_Full_Stack.pdf",
    "Software Engineer":          "Ben_Hankins_Full_Stack.pdf",
    "Solutions Engineer":         "Ben_Hankins_Solutions_feb26.pdf",
}


def extract_pdf_text(pdf_path: Path) -> str:
    """
    Extract raw text from a PDF file.

    pypdf reads each page and joins the text.
    Quality depends on how the PDF was created — text-based PDFs
    (like those exported from Word or Google Docs) work perfectly.
    Image-based PDFs (scanned documents) would need OCR instead.
    """
    reader = PdfReader(pdf_path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages).strip()


def load_resumes() -> dict[str, str]:
    """
    Load configured resumes and return {filename: text}.
    Fails loudly if a resume file is missing — better to know early.
    """
    resumes = {}
    for role, filename in ROLE_TO_RESUME.items():
        path = RESUME_DIR / filename
        if filename not in resumes:  # deduplicate (Full Stack appears twice)
            if not path.exists():
                raise FileNotFoundError(f"Resume not found: {path}")
            resumes[filename] = extract_pdf_text(path)
            print(f"  Loaded {filename} ({len(resumes[filename])} chars)")
    return resumes


# -------------------------------------------------------------------
# Embedding model
#
# BAAI/bge-small-en-v1.5:
#   - 33MB download (one time, cached after first run)
#   - Produces 384-dimensional vectors
#   - Fast, good quality for semantic search
#   - Runs entirely locally via ONNX (no GPU, no torch, no API calls)
# -------------------------------------------------------------------

_model = None  # module-level cache — load once, reuse

def get_model() -> TextEmbedding:
    global _model
    if _model is None:
        print("  Loading embedding model (downloads once, ~33MB)...")
        _model = TextEmbedding("BAAI/bge-small-en-v1.5")
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    """
    Convert a list of text strings into a list of embedding vectors.

    fastembed returns a generator, so we wrap in list().
    Each vector is a list of 384 floats.
    """
    model = get_model()
    return list(model.embed(texts))


# -------------------------------------------------------------------
# ChromaDB setup
#
# ChromaDB is a local vector database.
# - Persists to disk (data/chroma/) between runs
# - Collections are like tables — we use one per purpose
# - Each document stored with: id, embedding vector, metadata, text
# -------------------------------------------------------------------

def get_chroma_client() -> chromadb.Client:
    Path("data/chroma").mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path="data/chroma")


def build_resume_collection(client: chromadb.Client, resumes: dict[str, str]) -> chromadb.Collection:
    """
    Embed each resume and store in ChromaDB.

    We delete and recreate on each run so the collection
    always reflects the current resume files.
    """
    # Delete existing collection if it exists (fresh start)
    try:
        client.delete_collection("resumes")
    except Exception:
        pass

    collection = client.create_collection(
        name="resumes",
        metadata={"hnsw:space": "cosine"},  # use cosine similarity for comparisons
    )

    filenames = list(resumes.keys())
    texts = list(resumes.values())
    vectors = embed(texts)

    collection.add(
        ids=filenames,
        embeddings=vectors,
        documents=texts,
        metadatas=[{"filename": f} for f in filenames],
    )

    print(f"  Stored {len(filenames)} resume embeddings in ChromaDB")
    return collection


def score_job_fit(job_description: str, resume_filename: str, collection: chromadb.Collection) -> float:
    """
    Compute semantic similarity between a job description and a specific resume.

    How it works:
      1. Embed the job description → a vector
      2. Query ChromaDB for the closest resume to that vector
      3. Return the similarity score (0–1, higher = better fit)

    Cosine similarity: measures the angle between two vectors.
    1.0 = identical meaning, 0.0 = completely unrelated.
    ChromaDB returns distance, so we convert: score = 1 - distance.
    """
    job_vector = embed([job_description])[0]

    result = collection.query(
        query_embeddings=[job_vector],
        where={"filename": resume_filename},
        n_results=1,
    )

    distances = result.get("distances", [[]])[0]
    if not distances:
        return 0.0

    # ChromaDB cosine distance: 0 = identical, 2 = opposite
    # Convert to similarity score 0–1
    return round(1 - (distances[0] / 2), 3)


if __name__ == "__main__":
    print("=== Embed Stage Test ===\n")

    print("Loading resumes...")
    resumes = load_resumes()

    print("\nSetting up ChromaDB...")
    client = get_chroma_client()
    collection = build_resume_collection(client, resumes)

    # Quick sanity check: score a fake job description
    print("\nSanity check — scoring a fake 'Software Engineer' job...")
    fake_jd = "We are looking for a Full Stack Software Engineer with React, Node.js, and cloud infrastructure experience."
    score = score_job_fit(fake_jd, "Ben_Hankins_Full_Stack.pdf", collection)
    print(f"  Fit score vs Full Stack resume: {score}")

    score2 = score_job_fit(fake_jd, "Ben_Hankins_TPM.pdf", collection)
    print(f"  Fit score vs TPM resume:        {score2}")
    print(f"\n  (Full Stack should score higher than TPM for a SWE role)")
