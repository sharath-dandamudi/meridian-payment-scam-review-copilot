"""Embed and upsert the fictional approved-policy corpus into the configured namespace."""

from __future__ import annotations

from pathlib import Path

from copilot.pinecone_policy import ingest_policy_documents
from copilot.settings import Settings


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    count = ingest_policy_documents(Settings(), root / "knowledge_base" / "policy")
    print(f"Upserted {count} fictional policy documents.")


if __name__ == "__main__":
    main()
