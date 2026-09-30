import json
import sys


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: find_hyperdrive_id.py NAME")

    name = sys.argv[1]
    payload = json.load(sys.stdin)
    for item in payload.get("result", []):
        if item.get("name") == name:
            print(item["id"])
            return

    print("")


if __name__ == "__main__":
    main()
