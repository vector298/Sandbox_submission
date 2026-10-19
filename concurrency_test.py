"""4b: send copies of an action at (nearly) the same instant and record exactly what happened.
 
Every worker is a separate process with its own database connection. A barrier releases
them together, so the submits really do overlap.
"""
import collections
import json
import multiprocessing as mp
import os
import tempfile
import time
 
import app
from replay_fn import replay
 
ctx = mp.get_context("fork")
TRIALS = 100
 
 
# ------------------------------------------------------------ the real app (SQLite)
 
def db_worker(path, barrier, args, out):
    conn = app.connect(path)
    barrier.wait()
    try:
        out.put(app.submit_event(conn, *args)["verdict"])
    except Exception as err:
        out.put(f"error: {type(err).__name__}: {err}")
 
 
def run_db_trial(path, arg_list):
    barrier = ctx.Barrier(len(arg_list))
    out = ctx.Queue()
    procs = [ctx.Process(target=db_worker, args=(path, barrier, a, out)) for a in arg_list]
    for p in procs:
        p.start()
    verdicts = [out.get() for _ in procs]
    for p in procs:
        p.join()
    conn = app.connect(path)
    events = app.load_log(conn)
    scores, _ = replay(events)
    return sorted(verdicts), len(events), scores
 
 
def db_experiment(title, arg_list):
    shapes = collections.Counter()
    winners = collections.Counter()
    bad_rows = 0
    for _ in range(TRIALS):
        with tempfile.TemporaryDirectory() as d:
            verdicts, rows, scores = run_db_trial(os.path.join(d, "t.db"), arg_list)
        shapes[tuple(verdicts)] += 1
        winners[scores["B"] if arg_list[0][1] == "B" else scores["A"]] += 1
        if rows != 1:
            bad_rows += 1
    print(f"\n{title}  ({TRIALS} trials, {len(arg_list)} processes released together each time)")
    for shape, n in shapes.most_common():
        print(f"   verdicts {list(shape)}: {n} trials")
    print(f"   trials where the log did NOT end up with exactly one stored event: {bad_rows}")
    print(f"   final score of the team, by number of trials: {dict(winners)}")
 
 
# ------------------------------------------------------------ a naive version for comparison
 
def naive_submit(path, event, pause):
    """Check-then-append on a plain file: the obvious approach, with no lock and no transaction."""
    seen = set()
    if os.path.exists(path):
        with open(path) as f:
            seen = {json.loads(line)["id"] for line in f if line.strip()}
    if event["id"] in seen:
        return "duplicate"
    time.sleep(pause)   # 0 = no artificial delay
    with open(path, "a") as f:
        f.write(json.dumps(event) + "\n")
    return "saved"
 
 
def naive_worker(path, barrier, event, pause):
    barrier.wait()
    naive_submit(path, event, pause)
 
 
def naive_experiment(title, pause, trials):
    doubled = 0
    for _ in range(trials):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.jsonl")
            barrier = ctx.Barrier(2)
            event = {"id": "e12", "team": "A", "points": 25, "action": "ADD"}
            procs = [ctx.Process(target=naive_worker, args=(path, barrier, event, pause)) for _ in range(2)]
            for p in procs:
                p.start()
            for p in procs:
                p.join()
            with open(path) as f:
                lines = [line for line in f if line.strip()]
            if len(lines) > 1:
                doubled += 1
    print(f"\n{title}  ({trials} trials, 2 copies of e12 +25 released together)")
    print(f"   trials where e12 was stored twice (team A would show +50 instead of +25): {doubled}")
 
 
if __name__ == "__main__":
    same = ("e12", "A", "25", "ADD")
    db_experiment("SQLite app: the SAME action twice", [same, same])
    db_experiment("SQLite app: the SAME action 8 times", [same] * 8)
    db_experiment("SQLite app: two DIFFERENT actions reuse id e05 (+15 vs +99)",
                  [("e05", "B", "15", "ADD"), ("e05", "B", "99", "ADD")])
    naive_experiment("Naive file, no artificial delay", 0, 300)
    naive_experiment("Naive file, 20 ms between the check and the write", 0.02, 50)
    