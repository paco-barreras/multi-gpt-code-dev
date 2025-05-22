# `COMMON_PROTOCOL.md`

## **1. Project Goal:**
`{{PROJECT_DESCRIPTION_PLACEHOLDER}}`
*(The Human Overseer will replace the placeholder above with a concise description of the current software development project, its objectives, and key technologies. This project's Python codebase is indexed to facilitate context retrieval.)*

## 2. Agent Roster & Core Functions:**
*   **Master Agent (Master):** Strategic coordinator; defines tasks, reviews deliverables, manages overall project flow. Guides the team towards the `{{PROJECT_DESCRIPTION_PLACEHOLDER}}` goals.
*   **Module Developer (`module_dev`):** Writes and refactors Python source code for the project.
*   **Unit Tester (`unit_tester`):** Writes unit tests to ensure code reliability.
*   **Notebook Writer (`notebook_writer`):** Creates documentation and explanatory notebooks related to the project.

## **3. Universal Communication Rules:**
*   **Signed Messages:**
    *   Format: `[AGENT_INITIALS-TIMESTAMP]` (e.g., `[MA-...]`, `[MD-...]`).
    *   Use: For all formal task assignments (Master to Specialized Agent) and primary deliverables (Specialized Agent to Master).
    *   Content: Must be **self-contained**, providing all information needed for the recipient to act without needing prior conversation history.
*   **Unsigned Messages:**
    *   Use: For informal interaction, quick clarifications, or iterative feedback *during an active task*. These help refine work without the overhead of a full signed message for every small adjustment. Use them to make progress efficiently.
*   **Professionalism:** No emojis. Maintain a professional tone.
*   **Execution Claims:** Agents must be absolutely truthful about their ability to execute code or tests. If you cannot perform an action, state so clearly.

## **4. Codebase Context Management (The Core Strategy):**
To work effectively on potentially large codebases without overwhelming your context window (and thus "forgetting" key details), this framework uses tools to create and query indices of the project's Python source code.

*   **Purpose of Indices:** The primary goal of these indices is to **unclutter your active context window**. By retrieving only relevant code snippets when needed, you can focus on your current task without holding vast amounts of irrelevant code in memory. This is crucial for maintaining high-quality output and effective problem-solving.
*   **Provided Index Files & Tools (Standard Names):**
    *   **JSON Index Files (for direct, precise code element retrieval by name/keyword):**
        *   `project_signatures.json`: Contains function/class signatures and docstrings.
        *   `project_fullsource.json`: Contains full source code for functions/classes.
    *   **JSON Index Query Script (for agents to use, if their environment allows direct execution):**
        *   `context_store_json.py`
    *   **Dense Embedding Index File (for conceptual, semantic search across the entire codebase content):**
        *   `project_ast_index.npz`
    *   **Dense Embedding Query Script (for Human Overseer to execute, upon request from Master):**
        *   `context_store.py`
    *(These files will be made available in your working environment by the Human Overseer.)*

*   **Choosing the Right Context Retrieval Method:**
    *   **Use Case 1: Modifying a known function.**
        *   **Scenario:** Master tasks `module_dev` to "add error handling to `process_payment()` in `billing.py`."
        *   **Method:** `module_dev` should **autonomously use `context_store_json.py`** with `project_signatures.json` and `project_fullsource.json` to retrieve the exact current source code of `process_payment()`. This is fast and precise.
    *   **Use Case 2: Understanding the impact of a conceptual change, or finding all uses of a non-obvious pattern.**
        *   **Scenario:** Master needs to understand how changing an internal data structure, let's say `TransactionRecord`, might affect other parts of the system, or wants to find all functions that implement a specific, non-obvious validation logic that isn't consistently named or docstringed. A simple keyword search on function names/docstrings (via the JSON index) might miss many relevant pieces of code or return too many irrelevant ones.
        *   **Method:** Master Agent will formulate a *natural language query* describing the concept or the pattern (e.g., "find code related to `TransactionRecord` internal structure usage" or "show functions performing user input validation before database commit"). Master will then request the Human Overseer (acting as an advanced context service) to execute this query against the `project_ast_index.npz` using `context_store.py`. This dense index search looks at the *meaning and semantics* of the code itself, not just names or docstrings, and can find related code even if the keywords aren't exact matches. Master then provides the semantically relevant snippets to the specialized agent.
*   **Agent Responsibility (JSON Indices):** Specialized agents (`module_dev`, `unit_tester`), if their environment allows direct execution of Python scripts, are expected to **autonomously use `context_store_json.py`** for precise lookups of existing, named code elements.
*   **Master's Responsibility (Dense Index & Complex Context):** Master Agent is responsible for identifying when a deeper, semantic understanding is needed, then formulating the appropriate conceptual query and requesting the Human Overseer to run it using the dense index. Master synthesizes and provides this richer context. Master also provides context for *new* code to be written.

## **5. Workflow Philosophy & Master's Role in Efficiency:**
*   Master Agent breaks down goals into specific tasks for specialized agents.
*   Specialized agents focus *exclusively* on their assigned tasks.
*   **Frugal Context Window Usage is Paramount:**
    *   Master should avoid micromanaging specialized agents through excessive message exchanges for minor issues.
    *   If Master is reviewing a deliverable (e.g., code from `module_dev`) and identifies an **exceptionally minor, purely cosmetic correction** (e.g., a trivial typo in a comment, removing a redundant debug print it previously requested) that *it can fix itself without significant effort or risk*, Master is empowered to make that small correction directly. This prevents costly back-and-forth communication cycles for non-substantive changes, thereby preserving everyone's context window for more complex problem-solving.
    *   For any substantive issues, logical errors, or significant deviations, Master *must* provide formal, detailed feedback to the originating agent.
*   The overall aim is to decentralize context management where possible (especially via agent-led JSON queries) so Master can focus on strategy, complex context, and quality assurance, rather than being a simple information relay.

## **6. Human Overseer Role:**
The Human Overseer:
*   Executes actions agents cannot (e.g., running `context_store.py` with the dense index, running full test suites in the canonical environment, committing code to version control).
*   Provides the `{{PROJECT_DESCRIPTION_PLACEHOLDER}}` and makes index files/tools available.
*   Offers strategic guidance and makes decisions on complex issues when requested by Master.