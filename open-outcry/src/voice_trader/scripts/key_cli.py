"""Key management CLI.

    voice-trader-key create --label "my-app"
    voice-trader-key list
    voice-trader-key revoke <prefix>
"""

from __future__ import annotations

import argparse
import sys

from ..interop.auth import ApiKeyStore


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="voice-trader-key")
    p.add_argument("--file", default="config/api_keys.json",
                   help="path to the key store")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create")
    c.add_argument("--label", default="")

    sub.add_parser("list")

    r = sub.add_parser("revoke")
    r.add_argument("prefix")

    args = p.parse_args(argv)
    store = ApiKeyStore(args.file)

    if args.cmd == "create":
        key = store.create(args.label)
        print("New API key (shown once — store it safely):")
        print(key)
        return 0

    if args.cmd == "list":
        records = store.list()
        if not records:
            print("No API keys yet. Run `voice-trader-key create`.")
            return 0
        for r in records:
            status = "REVOKED" if r["revoked"] else "active"
            print(f"{r['prefix']}  {r['label'] or '(no label)':<20}  {r['created']}  {status}")
        return 0

    if args.cmd == "revoke":
        ok = store.revoke(args.prefix)
        print(f"Revoked {args.prefix}" if ok else f"No active key with prefix {args.prefix}")
        return 0 if ok else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
