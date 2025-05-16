# Code Context Store (`context_store.py`)

This script provides tools to build and query a dense, AST-based semantic index of a Python codebase. It uses SentenceTransformer models to embed code chunks (functions and classes) and allows for natural language querying to find relevant code snippets.

## Features

-   **AST-based Chunking:** Intelligently extracts functions and classes as individual, semantic code chunks.
-   **Dense Embeddings:** Uses SentenceTransformer models (e.g., `intfloat/e5-base-v2`) for creating vector embeddings.
-   **Command-Line Interface:**
    -   `build`: To create an index from a codebase.
    -   `query`: To search the created index using natural language.
-   **Programmatic API:** `get_code_context` function for integration into other Python tools.
-   **Caching:** In-memory caching for loaded index files and SentenceTransformer models to speed up subsequent queries.

## Requirements

-   Python 3.8+
-   `numpy`
-   `torch` (CPU version is sufficient)
-   `sentence-transformers`

Install dependencies:
```bash
pip install numpy torch sentence-transformers
