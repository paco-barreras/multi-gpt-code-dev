import json, ast
from pathlib import Path
from typing import Iterator, Any

# ---------- Helpers (no external deps) ----------

def _get_ast_node_source_segment(source_lines, node):
    try:
        return "".join(source_lines[node.lineno - 1: node.end_lineno])
    except Exception:
        return ""

def _extract_ast_chunks_from_file(py_file_path, repo_root_path):
    try:
        content = py_file_path.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines(True)
        tree = ast.parse(content, filename=str(py_file_path))
    except Exception:
        return
    rel = str(py_file_path.relative_to(repo_root_path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            snippet = _get_ast_node_source_segment(lines, node)
            if snippet:
                yield {
                    "file_path": rel,
                    "element_name": node.name,
                    "element_type": node.__class__.__name__,
                    "start_line": node.lineno,
                    "end_line": node.end_lineno,
                    "docstring": ast.get_docstring(node) or "",
                    "source_code": snippet,
                }

# ---------- JSON export / query ----------

def export_ast_chunks_to_json(repo_root_path, output_basename):
    repo, base = Path(repo_root_path), Path(output_basename)
    sigs, fulls = [], []
    for py in repo.rglob("*.py"):
        if ".ipynb_checkpoints" in py.parts or py.name.startswith("."):
            continue
        try:
            chunks = _extract_ast_chunks_from_file(py, repo)
        except (SyntaxError, UnicodeDecodeError):
            continue
        for c in chunks:
            src_lines = c["source_code"].splitlines()
            sig_lines = []
            for ln in src_lines:
                s = ln.lstrip()
                if s.startswith("@"):
                    sig_lines.append(ln)
                    continue
                if s.startswith(("def ", "async def ", "class ")):
                    sig_lines.append(ln)
                    break
            if sig_lines:
                sig_lines[0] = sig_lines[0].lstrip()
            signature = "\n".join(sig_lines)
            sigs.append({
                "file_path": c["file_path"],
                "element_name": c["element_name"],
                "element_type": c["element_type"],
                "signature": signature,
                "docstring": c["docstring"],
                "start_line": c["start_line"],
                "end_line": c["end_line"],
            })
            fulls.append({
                "file_path": c["file_path"],
                "element_name": c["element_name"],
                "element_type": c["element_type"],
                "source_code": c["source_code"],
            })
    sig_path = base.with_name(f"{base.name}_signatures.json")
    full_path = base.with_name(f"{base.name}_fullsource.json")
    with open(sig_path, "w", encoding="utf-8") as f:
        json.dump(sigs, f, ensure_ascii=False, indent=2)
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(fulls, f, ensure_ascii=False, indent=2)
    print(f"JSON context exported to {sig_path.resolve()} and {full_path.resolve()}")

def query_json_context(query, signatures_path, fullsource_path, k=3):
    tokens = {t.lower() for t in query.split() if t}
    with open(signatures_path, encoding="utf-8") as f:
        sigs = json.load(f)
    with open(fullsource_path, encoding="utf-8") as f:
        fulls = {(e["file_path"], e["element_name"]): e for e in json.load(f)}
    scored = []
    for e in sigs:
        text = f"{e['element_name']} {e['docstring']}".lower()
        hits = sum(1 for t in tokens if t in text)
        if hits:
            scored.append((hits, e["start_line"], e))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [{
        "file": e["file_path"],
        "element_name": e["element_name"],
        "element_type": e["element_type"],
        "lines": f"{e['start_line']}-{e['end_line']}",
        "docstring": e["docstring"],
        "signature": e["signature"],
        "snippet": fulls.get((e["file_path"], e["element_name"]), {}).get("source_code", ""),
    } for _, _, e in scored[:k]]

# ---------- Tiny CLI ----------

def main():
    import argparse, json as _json
    p = argparse.ArgumentParser("context_store_json")
    sp = p.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build-json")
    b.add_argument("--repo", required=True)
    b.add_argument("--output-base-name", required=True)
    q = sp.add_parser("query-json")
    q.add_argument("--signatures-file", required=True)
    q.add_argument("--source-file", required=True)
    q.add_argument("--query", required=True)
    q.add_argument("--k", type=int, default=3)
    a = p.parse_args()
    if a.cmd == "build-json":
        export_ast_chunks_to_json(a.repo, a.output_base_name)
    else:
        print(_json.dumps(query_json_context(a.query, a.signatures_file, a.source_file, a.k), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
