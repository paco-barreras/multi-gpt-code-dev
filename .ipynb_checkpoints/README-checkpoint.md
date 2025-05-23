# **AI-Assisted Development Framework with Advanced Context Management**

This project provides a framework and a suite of tools (`context_store.py`, `context_store_json.py`) designed to facilitate sophisticated, AI-assisted software development. It enables multiple specialized AI agents to collaborate on a Python codebase by leveraging advanced context retrieval mechanisms, thereby mitigating the inherent context window limitations of Large Language Models (LLMs).

The core of the context management system allows for:
1.  **Lightweight, Precise Context Retrieval:** Using JSON-based indices (`project_signatures.json`, `project_fullsource.json`) for direct lookup of Python functions and classes by name, primarily queried via `context_store_json.py`.
2.  **Dense, Semantic Context Retrieval:** Using AST-based chunking and SentenceTransformer embeddings (`project_ast_index.npz`) for conceptual, natural language searches across the codebase, primarily queried via `context_store.py`.
3.  **Prose Document Indexing:** (If `build_prose_index` functionality is used) Semantic indexing of Markdown and Jupyter Notebook content for documentation and broader project understanding.

This README focuses on the tools and the conceptual multi-agent setup. Detailed agent priming documents (`COMMON_PROTOCOL.md`, `MASTER_AGENT_PRIME.md`, etc.) govern agent behavior and interaction.

## Core Context Tools

### 1. `context_store_json.py` (Lightweight JSON Indexing)
Provides functionalities for creating and querying a lightweight, exact-match index of Python code elements.
*   **Features:**
    *   AST-based extraction of function/class signatures, docstrings, and full source code.
    *   Outputs to `project_signatures.json` and `project_fullsource.json`.
    *   Relies only on the Python standard library.
*   **CLI Usage:**
    *   **Build JSON Index:**
        ```bash
        python context_store_json.py build-json --repo <path_to_python_codebase> --output-base-name project
        ```
        *(This creates `project_signatures.json` and `project_fullsource.json`)*
    *   **Query JSON Index:**
        ```bash
        python context_store_json.py query-json --signatures-file project_signatures.json --source-file project_fullsource.json --query "function_name in file_name.py" --k 3
        ```
*   **Programmatic API:** `export_ast_chunks_to_json()`, `query_json_context()`.

### 2. `context_store.py` (Dense Semantic Indexing & Prose Indexing)
Provides tools to build and query dense, AST-based semantic indices of Python code and (optionally) prose documents.
*   **Features:**
    *   **Code Indexing:**
        *   Intelligently extracts Python functions and classes.
        *   Uses SentenceTransformer models (e.g., `intfloat/e5-base-v2`) for creating vector embeddings.
        *   Enables natural language querying for semantically similar code snippets.
    *   **Prose Indexing (Optional):**
        *   Indexes Markdown and Jupyter Notebook content, chunked by headings.
        *   Allows semantic search over documentation and other prose.
    *   **Caching:** In-memory caching for loaded index files and models.
*   **CLI Usage (Code Index):**
    *   **Build Dense Code Index:**
        ```bash
        python context_store.py build --repo <path_to_python_codebase> --index project_ast_index.npz --model intfloat/e5-base-v2
        ```
    *   **Query Dense Code Index:**
        ```bash
        python context_store.py query --index project_ast_index.npz --query "natural language description of code needed" --k 3
        ```
*   **CLI Usage (Prose Index - if implemented):**
    *   **Build Dense Prose Index:**
        ```bash
        python context_store.py build-prose --repo <path_to_docs_or_project> --output project_prose_index.npz --model intfloat/e5-base-v2
        ```
    *   **Query Dense Prose Index:**
        ```bash
        python context_store.py query-prose --index project_prose_index.npz --query "concept from documentation" --k 3
        ```
*   **Programmatic API:** `build_index()`, `get_code_context()`, `build_prose_index()`, `get_prose_context()`.

## Multi-Agent Framework Integration (Conceptual Overview)

This system is designed to be the backbone of a multi-agent development team, typically structured as follows:

*   **Human Overseer:** Initializes the project, provides high-level goals, makes index files and agent primes available, and executes actions agents cannot (e.g., running full test suites, committing code, running dense index queries).
*   **Master Agent (Master):**
    *   Receives project goals and orchestrates the specialized agents.
    *   Defines tasks, reviews deliverables, and ensures project coherence.
    *   Uses the "Task Delegation Checklist" (defined in its prime) to determine context strategy.
    *   Instructs specialized agents to use `context_store_json.py` for retrieving existing code elements.
    *   Formulates semantic queries for the dense index (`project_ast_index.npz`) and requests the Human Overseer to execute them via `context_store.py`, then provides the results to specialized agents.
*   **Specialized Agents (`module_dev`, `unit_tester`, `notebook_writer`):**
    *   Operate based on signed tasks from Master and their role-specific primes.
    *   Utilize a "Task Kick-off Checklist" to guide their actions, including context acquisition.
    *   **Crucially, if their environment allows, they directly execute `context_store_json.py query-json ...`** to retrieve context for existing Python code elements they are tasked to work on, using the provided `project_signatures.json` and `project_fullsource.json`. This minimizes Master's context burden.
    *   Refer to `COMMON_PROTOCOL.md` and their specific prime for detailed operational rules and interaction protocols.

### Workflow Example (Simplified):
1.  **Human Overseer:** Provides `COMMON_PROTOCOL.md`, role-specific primes, index files, and tool scripts to the agent environment. Sets a project goal.
2.  **Master Agent:** Decomposes goal. Identifies that `module_dev` needs to modify `function_A` in `module_X.py`.
3.  **Master Agent to `module_dev` (Signed Message):** "Task: Modify `function_A` in `module_X.py` to include new error handling for X. First, retrieve current source for `function_A` using `context_store_json.py query-json ...` (refer to `COMMON_PROTOCOL.md` for command structure if needed)."
4.  **`module_dev` (Internal):** Executes its "Task Kick-off Checklist." Runs the `query-json` command, gets `function_A`'s source. Implements changes.
5.  **`module_dev` to Master (Signed Message):** Delivers modified `function_A`.
6.  **Master Agent:** Reviews. If a broader impact analysis is needed, Master formulates a semantic query (e.g., "find all functions affected by changes to `function_A`'s return type") and asks Human to run it against `project_ast_index.npz`. Master uses these results to plan next steps or provide further context to agents.

This collaborative approach, underpinned by robust context retrieval tools, allows the AI team to tackle complex software development tasks more effectively.

## Requirements (for `context_store.py` dense indexing)

*   Python 3.8+
*   `numpy`
*   `torch` (CPU version is sufficient)
*   `sentence-transformers`
*   `nbformat` & `nbconvert` (for prose indexing of Jupyter Notebooks)

Install dependencies for dense indexing:
```bash
pip install numpy torch sentence-transformers nbformat nbconvert
```
(`context_store_json.py` has no external dependencies beyond the Python standard library).