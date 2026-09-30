import json
import os
import sys


def main():
    payload = json.load(sys.stdin)
    accounts = payload.get("result") or []
    preferred = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()

    if preferred:
        matches = [a for a in accounts if a.get("id") == preferred]
        if not matches:
            raise SystemExit(
                "Configured CLOUDFLARE_ACCOUNT_ID is not visible to the API token."
            )
        print(preferred)
        return

    if len(accounts) == 1:
        print(accounts[0]["id"])
        return

    if not accounts:
        raise SystemExit(
            "Cloudflare API token cannot see any accounts. Add Account Settings Read."
        )

    raise SystemExit(
        "Cloudflare API token can see multiple accounts. "
        "Set repository variable CLOUDFLARE_ACCOUNT_ID to select one."
    )


if __name__ == "__main__":
    main()
