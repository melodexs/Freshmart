#!/usr/bin/env bash
# Prints a random value suitable for JWT_SECRET or STORE_STAFF_KEY.
python3 -c "import secrets; print(secrets.token_hex(32))"
