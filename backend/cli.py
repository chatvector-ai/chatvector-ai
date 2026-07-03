"""ChatVector management CLI.

Usage:
    python -m backend.cli create-tenant-key --tenant <name> [--tenant-id <id>]

Commands
--------
create-tenant-key
    Create a new tenant and generate an API key for it.
    The raw API key is printed once and never stored — copy it immediately.
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

    args = parser.parse_args()

    if args.command == "create-tenant-key":
        asyncio.run(cmd_create_tenant_key(args.tenant, args.tenant_id))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
