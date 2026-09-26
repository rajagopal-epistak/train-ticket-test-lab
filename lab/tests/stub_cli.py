#!/usr/bin/env python3
"""Stand-in for kubectl, terraform, curl, make, sleep and date in the lab.sh tests.

Rules come from $STUB_RULES: {"<command>": [{"match": [substrings], "stdout": "...", "exit": 0}, ...]}.
The first rule whose substrings all occur in the joined arguments wins. A rule with "seq" answers its
calls in order and repeats the last item. For curl, the key is "<METHOD> <URL>", the answer goes to the
-o file, and "http" (default 200) is printed for -w. A rule with "exists" logs whether that path exists.
Every call is appended to $STUB_LOG as a JSON list.
"""
import json
import os
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
state = Path(os.environ["STUB_STATE"])

if name == "sleep":
    sys.exit(0)
if name == "date":
    clock = state / "clock"
    t = int(clock.read_text()) + 60 if clock.exists() else 1_000_000
    clock.write_text(str(t))
    print(t)
    sys.exit(0)

out_file = ""
if name == "curl":
    config = sys.stdin.read()
    method = args[args.index("-X") + 1]
    out_file = args[args.index("-o") + 1]
    key = f"{method} {args[-1]}"
    with open(state / "curl-stdin", "a") as f:
        f.write(config)
else:
    key = " ".join(args)

with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps([name, *args]) + "\n")

rules = json.loads(Path(os.environ["STUB_RULES"]).read_text()).get(name, [])
for i, rule in enumerate(rules):
    if all(token in key for token in rule["match"]):
        if "exists" in rule:
            with open(os.environ["STUB_LOG"], "a") as f:
                f.write(json.dumps(["exists", rule["exists"], Path(rule["exists"]).exists()]) + "\n")
        items = rule.get("seq") or [rule]
        counter = state / f"{name}-{i}"
        n = int(counter.read_text()) if counter.exists() else 0
        counter.write_text(str(n + 1))
        item = items[min(n, len(items) - 1)]
        if name == "curl":
            Path(out_file).write_text(item.get("stdout", ""))
            print(item.get("http", 200), end="")
            sys.exit(0)
        sys.stdout.write(item.get("stdout", ""))
        sys.exit(item.get("exit", 0))

if name == "curl":
    Path(out_file).write_text("{}")
    print(200, end="")
sys.exit(0)
