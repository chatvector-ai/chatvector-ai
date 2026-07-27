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
"""

from __future__ import annotations

import argparse
import asyncio
import sys


async def cmd_create_tenant_key(tenant_name: str, tenant_id: str | None) -> None:
    from services.api_key_service import create_api_key, create_tenant

    tenant = await create_tenant(name=tenant_name, tenant_id=tenant_id)
    raw_key, api_key = await create_api_key(tenant_id=tenant.id)

    print()
    print("=" * 60)
    print("Tenant created")
    print(f"  ID   : {tenant.id}")
    print(f"  Name : {tenant.name}")
    print()
    print("API key created")
    print(f"  Key ID : {api_key.id}")
    print(f"  Prefix : {api_key.prefix}")
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


async def cmd_list_tenant_keys(tenant_id: str) -> None:
    from services.api_key_service import list_tenant_keys

    keys = await list_tenant_keys(tenant_id=tenant_id)

    if not keys:
        print(f"No API keys found for tenant '{tenant_id}'.")
        return

    print()
    print(f"API keys for tenant '{tenant_id}':")
    print("-" * 60)
    print(f"{'ID':<38} {'Prefix':<10} {'Status':<10} Created")
    print("-" * 60)
    for key in keys:
        print(f"{str(key.id):<38} {key.prefix:<10} {key.status:<10} {key.created_at}")
    print()

async def cmd_revoke_tenant_key(tenant_id: str, key_id: str | None, prefix: str | None) -> None:
    from services.api_key_service import revoke_api_key

    if not key_id and not prefix:
        print("Error: must provide --key-id or --prefix")
        return

    success = await revoke_api_key(tenant_id=tenant_id, key_id=key_id, prefix=prefix)

    if success:
        print(f"Key revoked for tenant '{tenant_id}'.")
    else:
        print(f"No matching key found for tenant '{tenant_id}'.")

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

    args = parser.parse_args()

    if args.command == "create-tenant-key":
        asyncio.run(cmd_create_tenant_key(args.tenant, args.tenant_id))
    elif args.command == "list-tenant-keys":
        asyncio.run(cmd_list_tenant_keys(args.tenant_id))
    elif args.command == "revoke-tenant-key":
        asyncio.run(cmd_revoke_tenant_key(args.tenant_id, args.key_id, args.prefix))
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
