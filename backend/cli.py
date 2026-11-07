"""ChatVector management CLI.

Usage:
    python -m backend.cli create-tenant-key --tenant <name> [--tenant-id <id>]

Commands
--------
create-tenant-key
    Create a new tenant and generate an API key for it.
    The raw API key is printed once and never stored — copy it immediately.

list-tenant-keys
    List API keys for a tenant (id, prefix, status, created_at). Never
    returns the raw secret since it isn't stored.

revoke-tenant-key
    Revoke a key by id or prefix. Safe to run twice — revoking an
    already-revoked key is a no-op.

rotate-tenant-key
    Revoke an existing key and issue a new one for the same tenant.
    Prints the new raw key once.

set-tenant-key-expiry
    Set or clear expires_at on a key (ISO-8601 datetime, or "clear").

set-tenant-key-external-user-id
    Assign or clear external_user_id on a key.

load-eval-corpus
    Load a fixed corpus into one tenant through the production extract,
    chunk, embed, and store stages. Does not call the public upload route.
    Writes a manifest from stable logical keys to the document ids created
    for that run. A repeat run replaces only that tenant's documents.

eval
    Run retrieval evaluation/benchmarking against a query fixture dataset.
    Computes recall@k, MRR, and nDCG@k; supports comparing multiple
    retrieval config "arms" in one run and exporting a reproducible JSON
    artifact. Does not call answer generation unless --answers is set.
    That flag scores answer labels with generate_answer and is off by
    default. Optional --manifest resolves logical keys to document ids
    and refuses a chunk-setting mismatch before scoring. See DEVELOPMENT.md
    ("Retrieval evaluation") for the dataset and config-arm schema.

eval-conversations
    Play fixed multi-turn scripts against the eval tenant through in-process
    chat. Does not call the public chat route and does not upload documents.
    A script longer than its max_turns fails before the model is called.
    See DEVELOPMENT.md ("Conversational regression harness").
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path


def _parse_expires_at(value: str) -> datetime | None:
    if value.lower() == "clear":
        return None
    return datetime.fromisoformat(value)


def _print_raw_key_block(raw_key: str, api_key, *, action: str) -> None:
    print()
    print("=" * 60)
    print(action)
    print(f"  Key ID : {api_key.id}")
    print(f"  Prefix : {api_key.prefix}")
    if api_key.external_user_id:
        print(f"  External user ID : {api_key.external_user_id}")
    if api_key.expires_at:
        print(f"  Expires at : {api_key.expires_at}")
    print()
    print("Raw API key (shown once — copy it now):")
    print()
    print(f"  {raw_key}")
    print()
    print("=" * 60)
    print()
    print("Add to your client's Authorization header:")
    print(f"  Authorization: Bearer {raw_key}")
    print()


async def cmd_create_tenant_key(
    tenant_name: str,
    tenant_id: str | None,
    external_user_id: str | None,
    expires_at: datetime | None,
) -> None:
    from services.api_key_service import create_api_key, create_tenant

    tenant = await create_tenant(name=tenant_name, tenant_id=tenant_id)
    raw_key, api_key = await create_api_key(
        tenant_id=tenant.id,
        external_user_id=external_user_id,
        expires_at=expires_at,
    )

    print()
    print("=" * 60)
    print("Tenant created")
    print(f"  ID   : {tenant.id}")
    print(f"  Name : {tenant.name}")
    print()
    _print_raw_key_block(raw_key, api_key, action="API key created")


async def cmd_list_tenant_keys(tenant_id: str) -> None:
    from services.api_key_service import list_tenant_keys

    keys = await list_tenant_keys(tenant_id=tenant_id)

    if not keys:
        print(f"No API keys found for tenant '{tenant_id}'.")
        return

    print()
    print(f"API keys for tenant '{tenant_id}':")
    print("-" * 90)
    print(
        f"{'ID':<38} {'Prefix':<10} {'Status':<10} "
        f"{'External user':<16} {'Expires':<20} Created"
    )
    print("-" * 90)
    for key in keys:
        external_user = key.external_user_id or "-"
        expires = key.expires_at.isoformat() if key.expires_at else "-"
        print(
            f"{str(key.id):<38} {key.prefix:<10} {key.status:<10} "
            f"{external_user:<16} {expires:<20} {key.created_at}"
        )
    print()


async def cmd_revoke_tenant_key(
    tenant_id: str,
    key_id: str | None,
    prefix: str | None,
) -> None:
    from services.api_key_service import revoke_api_key

    if not key_id and not prefix:
        print("Error: must provide --key-id or --prefix")
        return

    success = await revoke_api_key(tenant_id=tenant_id, key_id=key_id, prefix=prefix)

    if success:
        print(f"Key revoked for tenant '{tenant_id}'.")
    else:
        print(f"No matching key found for tenant '{tenant_id}'.")


async def cmd_rotate_tenant_key(tenant_id: str, key_id: str) -> None:
    from services.api_key_service import rotate_api_key

    result = await rotate_api_key(tenant_id=tenant_id, key_id=key_id)
    if result is None:
        print(f"No matching key found for tenant '{tenant_id}'.")
        return

    raw_key, api_key = result
    _print_raw_key_block(raw_key, api_key, action="API key rotated")


async def cmd_set_tenant_key_expiry(
    tenant_id: str,
    key_id: str,
    expires_at: datetime | None,
) -> None:
    from services.api_key_service import set_api_key_expiry

    success = await set_api_key_expiry(
        tenant_id=tenant_id,
        key_id=key_id,
        expires_at=expires_at,
    )
    if success:
        if expires_at is None:
            print(f"Cleared expiry for key '{key_id}' on tenant '{tenant_id}'.")
        else:
            print(
                f"Set expiry for key '{key_id}' on tenant '{tenant_id}' "
                f"to {expires_at.isoformat()}."
            )
    else:
        print(f"No matching key found for tenant '{tenant_id}'.")


async def cmd_set_tenant_key_external_user_id(
    tenant_id: str,
    key_id: str,
    external_user_id: str | None,
) -> None:
    from services.api_key_service import set_api_key_external_user_id

    success = await set_api_key_external_user_id(
        tenant_id=tenant_id,
        key_id=key_id,
        external_user_id=external_user_id,
    )
    if success:
        if external_user_id is None:
            print(f"Cleared external_user_id for key '{key_id}' on tenant '{tenant_id}'.")
        else:
            print(
                f"Set external_user_id for key '{key_id}' on tenant '{tenant_id}' "
                f"to {external_user_id!r}."
            )
    else:
        print(f"No matching key found for tenant '{tenant_id}'.")


async def cmd_eval(
    dataset_path: str,
    tenant_id: str,
    k_values: list[int],
    config_paths: list[str],
    match_count: int,
    export_path: str | None,
    allow_cache: bool,
    manifest_path: str | None = None,
    answer_generation: bool = False,
) -> None:
    from core.config import config as core_config
    from services import context_service
    from services.eval_config import EffectiveRetrievalConfig
    from services.eval_fixtures import load_dataset
    from services.eval_service import diff_arms, run_eval

    dataset = load_dataset(dataset_path, manifest_path=manifest_path)
    answer_fn = None
    if answer_generation:
        from services.answer_service import generate_answer as answer_fn

    if config_paths:
        arms = []
        for raw_path in config_paths:
            raw = json.loads(Path(raw_path).read_text(encoding="utf-8"))
            arms.append(
                EffectiveRetrievalConfig(
                    label=raw.get("label", Path(raw_path).stem),
                    hybrid_retrieval_enabled=(
                        raw["hybrid_enabled"]
                        if "hybrid_enabled" in raw
                        else raw["hybrid_retrieval_enabled"]
                    ),
                    enable_reranking=(
                        raw["reranking_enabled"]
                        if "reranking_enabled" in raw
                        else raw["enable_reranking"]
                    ),
                    reranker_provider=raw.get("reranker_provider", "similarity"),
                    match_count=raw.get("match_count", match_count),
                    max_context_chars=raw.get(
                        "max_context_chars", context_service.MAX_CONTEXT_CHARS
                    ),
                    allow_embedding_cache=raw.get("allow_embedding_cache", allow_cache),
                    query_transformation_enabled=raw.get("query_transformation_enabled", False),
                    query_transformation_strategy=raw.get("query_transformation_strategy", "none"),
                    skip_history_transform=raw.get("skip_history_transform", True),
                )
            )
    else:
        arms = [
            EffectiveRetrievalConfig(
                label="current-config",
                hybrid_retrieval_enabled=core_config.HYBRID_RETRIEVAL_ENABLED,
                enable_reranking=core_config.ENABLE_RERANKING,
                reranker_provider=core_config.RERANKER_PROVIDER,
                match_count=match_count,
                max_context_chars=context_service.MAX_CONTEXT_CHARS,
                allow_embedding_cache=allow_cache,
            )
        ]

    result = await run_eval(
        dataset,
        arms,
        tenant_id=tenant_id,
        k_values=tuple(k_values),
        export_path=export_path,
        answer_generation=answer_generation,
        generate_answer=answer_fn,
    )

    print()
    print(
        f"Eval run {result.run_id} — dataset '{result.dataset_name}' "
        f"({len(dataset.queries)} queries)"
    )
    print("-" * 70)
    for arm in result.arms:
        metrics_str = ", ".join(
            f"{name}={value:.4f}" for name, value in arm.aggregate_metrics.items()
        )
        print(f"[{arm.config.label}] {metrics_str}")
    print()

    if len(result.arms) > 1:
        diffs = diff_arms(result.arms)
        differing = sum(1 for d in diffs if d["differs"])
        print(
            f"Compare: {differing}/{len(diffs)} queries produced different "
            "candidates across arms"
        )
        print()

    if export_path:
        print(f"Exported full run artifact to {export_path}")


async def cmd_load_eval_corpus(
    corpus_dir: str,
    declaration_path: str,
    tenant_id: str,
    manifest_path: str,
) -> None:
    from services.eval_corpus import load_eval_corpus

    manifest = await load_eval_corpus(
        corpus_dir,
        declaration_path,
        tenant_id,
        manifest_path,
    )
    count = len(manifest["documents"])
    print(f"Loaded {count} documents into tenant {tenant_id!r}.")
    print(f"Manifest: {manifest_path}")


async def cmd_eval_conversations(
    scenarios_dir: str,
    tenant_id: str,
    manifest_path: str,
    export_dir: str,
) -> None:
    from services.conversation_scenarios import (
        ConversationScenarioError,
        run_checked_in_conversations,
    )

    result = await run_checked_in_conversations(
        scenarios_dir,
        tenant_id=tenant_id,
        manifest_path=manifest_path,
        artifact_dir=export_dir,
    )
    failed = 0
    for record in result.scenarios:
        state = "passed" if record.passed else "failed"
        print(f"{state} {record.scenario_id} -> {record.artifact_path}")
        if record.error:
            failed += 1
            print(f"  {record.error}")
    if failed:
        raise ConversationScenarioError(f"{failed} scenario(s) failed")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="backend.cli",
        description="ChatVector management commands",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser(
        "create-tenant-key",
        help="Create a tenant and generate an API key",
    )
    create_parser.add_argument(
        "--tenant",
        required=True,
        metavar="NAME",
        help="Human-readable tenant name (e.g. 'demo' or 'Acme Corp')",
    )
    create_parser.add_argument(
        "--tenant-id",
        metavar="ID",
        default=None,
        help="Optional stable tenant identifier (defaults to slugified name)",
    )
    create_parser.add_argument(
        "--external-user-id",
        metavar="ID",
        default=None,
        help="Optional developer-side user identifier to store with the key",
    )
    create_parser.add_argument(
        "--expires-at",
        metavar="ISO",
        default=None,
        help="Optional ISO-8601 expiration datetime for the key",
    )

    list_parser = subparsers.add_parser(
        "list-tenant-keys",
        help="List API keys for a tenant",
    )
    list_parser.add_argument("--tenant-id", required=True, metavar="ID")

    revoke_parser = subparsers.add_parser(
        "revoke-tenant-key",
        help="Revoke an API key by id or prefix",
    )
    revoke_parser.add_argument("--tenant-id", required=True, metavar="ID")
    revoke_parser.add_argument("--key-id", metavar="ID", default=None)
    revoke_parser.add_argument("--prefix", metavar="PREFIX", default=None)

    rotate_parser = subparsers.add_parser(
        "rotate-tenant-key",
        help="Rotate an API key (revoke old, issue new)",
    )
    rotate_parser.add_argument("--tenant-id", required=True, metavar="ID")
    rotate_parser.add_argument("--key-id", required=True, metavar="ID")

    expiry_parser = subparsers.add_parser(
        "set-tenant-key-expiry",
        help="Set or clear API key expiration",
    )
    expiry_parser.add_argument("--tenant-id", required=True, metavar="ID")
    expiry_parser.add_argument("--key-id", required=True, metavar="ID")
    expiry_parser.add_argument(
        "--expires-at",
        required=True,
        metavar="ISO",
        help="ISO-8601 datetime, or 'clear' to remove expiration",
    )

    external_user_parser = subparsers.add_parser(
        "set-tenant-key-external-user-id",
        help="Set or clear external_user_id on an API key",
    )
    external_user_parser.add_argument("--tenant-id", required=True, metavar="ID")
    external_user_parser.add_argument("--key-id", required=True, metavar="ID")
    external_user_parser.add_argument(
        "--external-user-id",
        required=True,
        metavar="ID",
        help="Developer-side user identifier, or 'clear' to remove",
    )

    eval_parser = subparsers.add_parser(
        "eval",
        help="Run retrieval evaluation/benchmarking against a query fixture dataset",
    )
    eval_parser.add_argument(
        "--dataset", required=True, metavar="PATH", help="Path to a query fixture JSON dataset"
    )
    eval_parser.add_argument("--tenant-id", required=True, metavar="ID")
    eval_parser.add_argument(
        "--k",
        default="5,10",
        metavar="K1,K2",
        help="Comma-separated k values for recall@k/nDCG@k (default: 5,10)",
    )
    eval_parser.add_argument(
        "--config",
        action="append",
        default=[],
        metavar="PATH",
        dest="config_paths",
        help=(
            "Path to an arm config JSON file; repeat for multiple arms "
            "(compare mode). Omit to run the current process config as a "
            "single arm."
        ),
    )
    eval_parser.add_argument(
        "--match-count",
        type=int,
        default=10,
        metavar="N",
        help="Number of chunks to retrieve per document (default: 10)",
    )
    eval_parser.add_argument(
        "--export",
        default=None,
        metavar="PATH",
        dest="export_path",
        help="Write full run artifact (config snapshots + metrics) as JSON to PATH",
    )
    eval_parser.add_argument(
        "--allow-cache",
        action="store_true",
        help="Allow the embedding cache during eval (default: forced off for reproducibility)",
    )
    eval_parser.add_argument(
        "--manifest",
        default=None,
        metavar="PATH",
        help=(
            "Corpus manifest mapping logical keys to this run's document ids. "
            "Chunk settings must match the question file or the run stops before scoring."
        ),
    )
    eval_parser.add_argument(
        "--answers",
        action="store_true",
        help=(
            "Call generate_answer for rows with answer labels and score those labels. "
            "Off by default."
        ),
    )

    load_parser = subparsers.add_parser(
        "load-eval-corpus",
        help="Load a fixed evaluation corpus into one tenant",
    )
    load_parser.add_argument(
        "--corpus-dir",
        required=True,
        metavar="PATH",
        help="Directory of corpus files named by the declaration",
    )
    load_parser.add_argument(
        "--declaration",
        required=True,
        metavar="PATH",
        help="JSON file of logical keys, file names, metadata, and chunk settings",
    )
    load_parser.add_argument("--tenant-id", required=True, metavar="ID")
    load_parser.add_argument(
        "--manifest",
        required=True,
        metavar="PATH",
        help="Where to write the logical-key to document-id manifest",
    )

    conversations_parser = subparsers.add_parser(
        "eval-conversations",
        help="Play fixed multi-turn scripts against the eval corpus",
    )
    conversations_parser.add_argument(
        "--scenarios",
        required=True,
        metavar="PATH",
        help="Directory of fixed conversation scripts",
    )
    conversations_parser.add_argument("--tenant-id", required=True, metavar="ID")
    conversations_parser.add_argument(
        "--manifest",
        required=True,
        metavar="PATH",
        help="Corpus manifest mapping logical keys to this run's document ids",
    )
    conversations_parser.add_argument(
        "--export",
        required=True,
        metavar="PATH",
        dest="export_dir",
        help="Directory where each scenario's trace and config is written",
    )

    args = parser.parse_args()

    if args.command == "create-tenant-key":
        expires_at = (
            _parse_expires_at(args.expires_at) if args.expires_at else None
        )
        asyncio.run(
            cmd_create_tenant_key(
                args.tenant,
                args.tenant_id,
                args.external_user_id,
                expires_at,
            )
        )
    elif args.command == "list-tenant-keys":
        asyncio.run(cmd_list_tenant_keys(args.tenant_id))
    elif args.command == "revoke-tenant-key":
        asyncio.run(
            cmd_revoke_tenant_key(args.tenant_id, args.key_id, args.prefix)
        )
    elif args.command == "rotate-tenant-key":
        asyncio.run(cmd_rotate_tenant_key(args.tenant_id, args.key_id))
    elif args.command == "set-tenant-key-expiry":
        asyncio.run(
            cmd_set_tenant_key_expiry(
                args.tenant_id,
                args.key_id,
                _parse_expires_at(args.expires_at),
            )
        )
    elif args.command == "set-tenant-key-external-user-id":
        external_user_id = args.external_user_id
        if external_user_id.lower() == "clear":
            external_user_id = None
        asyncio.run(
            cmd_set_tenant_key_external_user_id(
                args.tenant_id,
                args.key_id,
                external_user_id,
            )
        )
    elif args.command == "eval":
        from services.eval_fixtures import EvalDatasetError

        k_values = [int(x) for x in args.k.split(",") if x.strip()]
        try:
            asyncio.run(
                cmd_eval(
                    args.dataset,
                    args.tenant_id,
                    k_values,
                    args.config_paths,
                    args.match_count,
                    args.export_path,
                    args.allow_cache,
                    args.manifest,
                    answer_generation=args.answers,
                )
            )
        except EvalDatasetError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
    elif args.command == "load-eval-corpus":
        from services.eval_corpus import EvalCorpusError

        try:
            asyncio.run(
                cmd_load_eval_corpus(
                    args.corpus_dir,
                    args.declaration,
                    args.tenant_id,
                    args.manifest,
                )
            )
        except EvalCorpusError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
    elif args.command == "eval-conversations":
        from services.conversation_scenarios import ConversationScenarioError

        try:
            asyncio.run(
                cmd_eval_conversations(
                    args.scenarios,
                    args.tenant_id,
                    args.manifest,
                    args.export_dir,
                )
            )
        except ConversationScenarioError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
