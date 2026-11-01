"""
Sliding-window chunking on top of the per-page/per-section units produced by
loaders.py, using LangChain's RecursiveCharacterTextSplitter (splits on
paragraph -> sentence -> word boundaries, in that preference order, so
chunks stay semantically coherent instead of cutting mid-sentence).
"""
from langchain.text_splitter import RecursiveCharacterTextSplitter

from app import config


def chunk_units(units: list[dict]) -> list[dict]:
    """units: output of loaders.load_document(). Returns a flat list of
    chunk dicts: {text, section_label, page_number, chunk_index}."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = []
    idx = 0
    for unit in units:
        pieces = splitter.split_text(unit["text"])
        for piece in pieces:
            if not piece.strip():
                continue
            chunks.append({
                "text": piece.strip(),
                "section_label": unit.get("section_label"),
                "page_number": unit.get("page_number"),
                "chunk_index": idx,
            })
            idx += 1
    return chunks
