"""Problem 5c: how long do the two methods take?
 
Input pattern (fixed seed, identical list for both methods):
    3 teams. 80% ADD with a new id and 3 random teams, points -50..100;
    12% UNDO of a random earlier ADD (80% from the owning team, 20% from another team);
    4% exact retry of an earlier ADD; 4% conflicting copy (same id, points + 1).
 
Two request patterns:
    END   one leaderboard request after the last event.
    LIVE  a leaderboard request after every 10th event (N / 10 requests).
 
Replay method:      append the event to the log; on a request call leaderboard_replay(log).
Incremental method: lb.apply(event) for every event; on a request call lb.standings().
Both methods process every event and answer every request; only the work differs.
"""
import os
import platform
import random
import statistics
import sys
import time
 
from ranking import IncrementalLeaderboard, leaderboard_replay
 
 
def make_events(n, seed=12345):
    rng = random.Random(seed)
    events, adds = [], []
    for row in range(1, n + 1):
        roll = rng.random()
        if roll < 0.80 or not adds:
            e = {"row": row, "id": f"e{row}", "team": rng.choice("ABC"), "points": rng.randint(-50, 100),
                 "action": "ADD", "refers_to": None}
            adds.append(e)
        elif roll < 0.92:
            target = rng.choice(adds)
            team = target["team"] if rng.random() < 0.8 else rng.choice("ABC")
            e = {"row": row, "id": f"u{row}", "team": team, "points": 0, "action": "UNDO", "refers_to": target["id"]}
        elif roll < 0.96:
            e = dict(rng.choice(adds), row=row)
        else:
            old = rng.choice(adds)
            e = dict(old, row=row, points=old["points"] + 1)
        events.append(e)
    return events
 
 
def run_replay(events, every):
    log, last = [], None
    for i, e in enumerate(events, start=1):
        log.append(e)
        if i % every == 0 or i == len(events):
            last = leaderboard_replay(log)
    return last
 
 
def run_incremental(events, every):
    lb, last = IncrementalLeaderboard(), None
    for i, e in enumerate(events, start=1):
        lb.apply(e)
        if i % every == 0 or i == len(events):
            last = lb.standings()
    return last
 
 
def timed(fn, events, every, repeats):
    fn(events, every)                       
    runs = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn(events, every)
        runs.append((time.perf_counter() - start) * 1000)
    return statistics.median(runs), min(runs), max(runs)
 
 
def cpu_model():
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"
 
 
def memory_gb():
    try:
        with open("/proc/meminfo") as f:
            return int(f.readline().split()[1]) / 1024 / 1024
    except (OSError, ValueError):
        return float("nan")
 
 
if __name__ == "__main__":
    print(f"Machine: {cpu_model()}, {os.cpu_count()} logical CPUs, {memory_gb():.1f} GB RAM")
    print(f"System:  {platform.platform()}, Python {sys.version.split()[0]} (single process, no other load started by the test)")
    print("Method:  time.perf_counter, one untimed warm-up, median of the repeats (min-max in brackets), milliseconds")
    print()
    rows = []
    for n in (100, 1000, 10000):
        events = make_events(n)
        assert run_replay(events, 10) == run_incremental(events, 10), "the two methods disagree"
        for label, every in (("END  (1 request)", n), ("LIVE (1 request per 10 events)", 10)):
            repeats = 3 if (n == 10000 and every == 10) else 5
            r = timed(run_replay, events, every, repeats)
            i = timed(run_incremental, events, every, repeats)
            rows.append((n, label, n // every, r, i))
            print(f"N={n:>6}  {label:<32} requests={n // every:>5}  "
                  f"replay {r[0]:>10.2f} ms [{r[1]:.2f}-{r[2]:.2f}]   "
                  f"incremental {i[0]:>8.2f} ms [{i[1]:.2f}-{i[2]:.2f}]   "
                  f"replay is {r[0] / i[0]:>6.1f}x slower", flush=True)
    print()
    print("Final standings agree at every N: yes (asserted before timing)")