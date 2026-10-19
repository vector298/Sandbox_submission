"""4c: kill the program at an exact moment, restart, retry, and look for lost or doubled points.
 
APP_TEST_CRASH=after_commit  -> the process dies right after COMMIT, before it prints "SAVED"
APP_TEST_CRASH=before_commit -> the process dies right before COMMIT
os._exit() kills the process like `kill -9`. It does NOT simulate a power cut or a failing disk.
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
 
 
def run(db, args, crash=None):
    env = dict(os.environ, APP_DB=db)
    env.pop("APP_TEST_CRASH", None)
    if crash:
        env["APP_TEST_CRASH"] = crash
    r = subprocess.run([sys.executable, "app.py", *args], capture_output=True, text=True, env=env)
    out = (r.stdout + r.stderr).strip() or "(no output)"
    print(f"$ {'APP_TEST_CRASH=' + crash + ' ' if crash else ''}python app.py {' '.join(args)}")
    print(f"  exit {r.returncode}: {out}")
    return r.returncode, out
 
 
def stored_events(db):
    return sqlite3.connect(db).execute("SELECT COUNT(*) FROM events").fetchone()[0]
 
 
def integrity(db):
    return sqlite3.connect(db).execute("PRAGMA integrity_check").fetchone()[0]
 
 
with tempfile.TemporaryDirectory() as d:
    db = os.path.join(d, "crash.db")
 
    print("=== A. crash AFTER commit, before the user is told ===")
    run(db, ["submit", "c1", "A", "25", "ADD"], crash="after_commit")
    run(db, ["score", "A"])
    print("  (the user never saw SAVED, so they retry)")
    run(db, ["submit", "c1", "A", "25", "ADD"])
    run(db, ["score", "A"])
    print(f"  events stored for c1: {stored_events(db)}")
 
    print("\n=== B. crash BEFORE commit ===")
    run(db, ["submit", "c2", "B", "40", "ADD"], crash="before_commit")
    run(db, ["score", "B"])
    run(db, ["explain", "c2"])
    print(f"  leftover journal file after the next start: {os.path.exists(db + '-journal')}")
    run(db, ["submit", "c2", "B", "40", "ADD"])
    run(db, ["score", "B"])
 
    print("\n=== C. five crashes after commit, then every submit retried (twice) ===")
    for i in range(1, 6):
        subprocess.run([sys.executable, "app.py", "submit", f"k{i}", "C", "10", "ADD"],
                       env=dict(os.environ, APP_DB=db, APP_TEST_CRASH="after_commit"), capture_output=True)
    print("  after the five crashes (user was told nothing):")
    run(db, ["score", "C"])
    for attempt in (1, 2):
        for i in range(1, 6):
            subprocess.run([sys.executable, "app.py", "submit", f"k{i}", "C", "10", "ADD"],
                           env=dict(os.environ, APP_DB=db), capture_output=True)
    print("  after retrying all five ids twice:")
    run(db, ["score", "C"])
 
    print("\n=== D. the user retries after a crash but types a different amount ===")
    run(db, ["submit", "c9", "A", "25", "ADD"], crash="after_commit")
    run(db, ["submit", "c9", "A", "30", "ADD"])
    run(db, ["score", "A"])
 
    print("\n=== final checks ===")
    print(f"  stored events: {stored_events(db)} (expected 1 + 1 + 5 + 1 = 8)")
    print(f"  PRAGMA integrity_check: {integrity(db)}")
    run(db, ["leaderboard"])