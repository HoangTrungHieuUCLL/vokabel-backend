#!/usr/bin/env python
"""Hash a password for APP_PASSWORD_HASH. Usage: python scripts/hash_password.py <password>"""

import sys

import bcrypt


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python scripts/hash_password.py <password>", file=sys.stderr)
        sys.exit(1)
    print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode())


if __name__ == "__main__":
    main()
