"""4d: feed the app bad input and record what happens (exit code and message)."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
 
 
def run(db, args, extra_env=None, show_cmd=None):
    env = dict(os.environ, APP_DB=db, **(extra_env or {}))
    env.pop("APP_TEST_CRASH", None)
    r = subprocess.run([sys.executable, "app.py", *args], capture_output=True, text=True, env=env, timeout=60)
    out = (r.stdout + r.stderr).strip().replace("\n", " | ")
    label = show_cmd or " ".join(repr(a) if a == "" or " " in a else a for a in args)
    if len(out) > 230:
        out = out[:230] + f"... [{len(out)} characters in total]"
    print(f"$ app.py {label}\n    exit {r.returncode}: {out}")
    return r.returncode, out
 
 
def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:12]
 
 
def count(db):
    return sqlite3.connect(db).execute("SELECT COUNT(*) FROM events").fetchone()[0]
 
 
with tempfile.TemporaryDirectory() as d:
    db = os.path.join(d, "f.db")
 
    print("=== 1. missing or unknown team ===")
    run(db, ["submit", "m1", "5", "ADD"])                     # one argument short: team missing
    run(db, ["submit", "m2", "", "5", "ADD"])                 # empty team
    run(db, ["submit", "m3", "D", "5", "ADD"])                # unknown team
    run(db, ["submit", "m4", "a", "5", "ADD"])                # lower-case typo
    run(db, ["score", "D"])
    run(db, ["score", ""])
    print(f"  events stored after all of the above: {count(db)}")
 
    print("\n=== 2. very large or odd input ===")
    run(db, ["submit", "b1", "A", str(10 ** 30), "ADD"], show_cmd="submit b1 A 10**30 ADD")
    run(db, ["submit", "b2", "A", "1001", "ADD"])
    run(db, ["submit", "b3", "A", "-1001", "ADD"])
    run(db, ["submit", "b4", "A", "9" * 100000, "ADD"], show_cmd="submit b4 A <100,000 nines> ADD")
    run(db, ["submit", "b5", "A", "1e3", "ADD"])
    run(db, ["submit", "b6", "A", "5.5", "ADD"])
    run(db, ["submit", "b7", "A", "abc", "ADD"])
    run(db, ["submit", "x" * 10000, "A", "5", "ADD"], show_cmd="submit <id of 10,000 characters> A 5 ADD")
    run(db, ["submit", "b8", "Z" * 50000, "5", "ADD"], show_cmd="submit b8 <team of 50,000 characters> 5 ADD")
    run(db, ["submit", "b9", "A", "5", "ADD" * 5000], show_cmd="submit b9 A 5 <action of 15,000 characters>")
    run(db, ["submit", "u1", "A", "0", "UNDO"])
    run(db, ["submit", "u2", "A", "5", "ADD", "e01"])
    run(db, ["submit", "u3", "A", "7", "UNDO", "e01"])
    run(db, ["submit", "u4", "A", "0", "UNDO", "u4"])
    print(f"  events stored after all of the above: {count(db)}")
    size = os.path.getsize(db)
    print(f"  database size after these rejected inputs: {size} bytes")
 
    print("\n=== 3. malformed files ===")
    bad_db = os.path.join(d, "garbage.db")
    with open(bad_db, "w") as f:
        f.write("this is not a database\n" * 50)
    before = sha(bad_db)
    run(bad_db, ["score", "A"])
    run(bad_db, ["submit", "g1", "A", "5", "ADD"])
    print(f"  garbage file unchanged by the app: {sha(bad_db) == before}")
 
    truncated = os.path.join(d, "truncated.db")
    run(truncated, ["submit", "t1", "A", "5", "ADD"])
    raw = open(truncated, "rb").read()
    with open(truncated, "wb") as f:
        f.write(raw[:300])        # cut a real database file short
    run(truncated, ["score", "A"])
 
    cases = {
        "not_json.json": "{ this is not json",
        "cut_off.json": '{"transactions": [{"id": "i1", "team": "A", "points": 5, "action": "ADD"},',
        "wrong_shape.json": '{"events": 5}',
        "bad_entries.json": json.dumps({"transactions": [
            {"id": "i1", "team": "A", "points": 5, "action": "ADD"},
            {"id": "i2", "team": "D", "points": 5, "action": "ADD"},
            {"id": "i3", "team": "A", "points": "lots", "action": "ADD"},
            {"id": "i4", "team": "A", "action": "ADD"},
            "just a string",
            {"id": "i5", "team": "B", "points": 7, "action": "ADD"}]}),
        "huge_number.json": '{"transactions": [{"id": "h1", "team": "A", "points": ' + "9" * 6000 + ', "action": "ADD"}]}',
    }
    for name, text in cases.items():
        path = os.path.join(d, name)
        with open(path, "w") as f:
            f.write(text)
        run(db, ["import", path], show_cmd=f"import {name}")
    run(db, ["import", os.path.join(d, "missing.json")], show_cmd="import missing.json")
    print(f"  events stored after the malformed imports: {count(db)} (expected 2: i1 and i5)")
 
    print("\n=== 4. repeated retries ===")
    db2 = os.path.join(d, "r.db")
    verdicts = {}
    for _ in range(50):
        _, out = (lambda: (0, subprocess.run([sys.executable, "app.py", "submit", "r1", "A", "25", "ADD"],
                                              capture_output=True, text=True,
                                              env=dict(os.environ, APP_DB=db2)).stdout.split(":")[0]))()
        verdicts[out] = verdicts.get(out, 0) + 1
    print(f"  50 identical submits of r1: {verdicts}")
    run(db2, ["score", "A"])
    print(f"  events stored: {count(db2)}")
    for _ in range(20):
        subprocess.run([sys.executable, "app.py", "submit", "r1", "A", "99", "ADD"],
                       capture_output=True, env=dict(os.environ, APP_DB=db2))
    run(db2, ["score", "A"])
    run(db2, ["explain", "r1"])
 
    print("\n=== 5. database busy (another program is holding the write lock) ===")
    db3 = os.path.join(d, "busy.db")
    run(db3, ["submit", "w1", "A", "5", "ADD"])
    holder = sqlite3.connect(db3, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    started = time.time()
    run(db3, ["submit", "w2", "A", "5", "ADD"], extra_env={"APP_BUSY_TIMEOUT": "0.5"})
    print(f"  gave up after {time.time() - started:.1f} s (including Python start-up)")
    holder.execute("ROLLBACK")
    run(db3, ["submit", "w2", "A", "5", "ADD"])
    run(db3, ["score", "A"])