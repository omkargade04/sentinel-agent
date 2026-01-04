
import hashlib

def generate_symbol_version_id(
    *,
    commit_sha: str | None,
    relative_path: str,
    kind: str,
    name: str,
    qualified_name: str | None,
    start_line: int,
    end_line: int,
) -> str:
    """
    Generate a snapshot-scoped identifier for a symbol instance.

    This ID is designed for:
    - PR hunk -> symbol mapping
    - inline comment anchoring
    - deterministic upserts within a single repo snapshot

    It is expected to change when a symbol moves or its span changes.
    """
    ident = qualified_name or name
    if not ident:
        raise ValueError("name or qualified_name must be provided")
    sha_part = commit_sha or ""
    canonical = f"{sha_part}::{relative_path}::{kind}::{ident}::{start_line}:{end_line}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_ast_fingerprint_from_types(
    node_types: list[str],
) -> str:
    """
    Create a semantic-ish fingerprint from an AST subtree reduced to node type sequence.

    Caller is responsible for producing a stable traversal order (e.g., pre-order).
    This tends to be resilient to whitespace and formatting, and can survive some refactors,
    but will change when the syntactic structure meaningfully changes.
    """
    payload = "\n".join(node_types)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_stable_symbol_id(
    *,
    repo_id: str,
    kind: str,
    qualified_name: str | None,
    name: str,
    fingerprint: str | None,
) -> str:
    """
    Generate a cross-snapshot stable id for a logical symbol.

    In a production system, the stable id is ideally reused via a resolver that matches
    symbols across snapshots (qualified_name -> fingerprint -> fuzzy match).

    For Sentinel v1 (no DB-backed resolver yet), we derive a stable key preferring
    fingerprint (rename/move tolerant) and fall back to qualified/name when fingerprint
    is unavailable.
    """
    stable_key = fingerprint or qualified_name or name
    if not stable_key:
        raise ValueError("fingerprint or qualified_name or name must be provided")
    canonical = f"{repo_id}::{kind}::{stable_key}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# Backward-compatible alias (snapshot-scoped).
def generate_symbol_id(
    *,
    relative_path: str,
    kind: str,
    name: str,
    qualified_name: str | None,
    start_line: int,
    end_line: int,
    commit_sha: str | None = None,
) -> str:
    return generate_symbol_version_id(
        commit_sha=commit_sha,
        relative_path=relative_path,
        kind=kind,
        name=name,
        qualified_name=qualified_name,
        start_line=start_line,
        end_line=end_line,
    )