"""Problem 5a and 5b: hand-derived rankings, then a differential test of the two solutions.
 
The expected rankings below were worked out by hand from the score traces (written in the
comments) BEFORE running either solution.
"""
import random
 
from ranking import FIRST_EVER, IncrementalLeaderboard, leaderboard_replay
from replay import replay
 
 
def ev(row, id_, team, points, action="ADD", refers_to=None):
    return {"row": row, "id": id_, "team": team, "points": points, "action": action, "refers_to": refers_to}
 
 
def order(standings):
    return [s["team"] for s in standings]
 
 
def incremental(events, **kw):
    lb = IncrementalLeaderboard(**kw)
    for e in events:
        lb.apply(e)
    return lb.standings()
 
 
def total_and_alphabet(events):
    scores, _ = replay(events)
    return sorted(scores, key=lambda t: (-scores[t], t))
 
 
# ---------------------------------------------------------------- 5a: three histories
#
# H1  1: B -5     scores after: A 0,  B -5, C 0
#     2: A -5                   A -5, B -5, C 0      B reached -5 at 1, A reached -5 at 2
#     3: C +3                   A -5, B -5, C 3
#     C leads. A and B tie at -5; B got there first. Correct: C, B, A.
# H2  1: A +50    scores after: A 50, B 0,  C 0
#     2: B +50                  A 50, B 50, C 0
#     3: A +10                  A 60, B 50, C 0
#     4: undo of 3              A 50, B 50, C 0      A left 50 at 3 and RETURNED at 4. B has held 50 since 2.
#     A and B tie at 50. A's time is now 4, B's is 2. Correct: B, A, C.
# H3  1: A +5     scores after: A 5,  B 0,  C 0
#     2: undo of 1              A 0,  B 0,  C 0      A returned to 0 at 2. B and C never moved (time 0).
#     Everyone is on 0. B and C share time 0, so team id decides: B before C. A is last. Correct: B, C, A.
 
HISTORIES = {
    "H1 equal negative totals, reached at different times": (
        [ev(1, "e1", "B", -5), ev(2, "e2", "A", -5), ev(3, "e3", "C", 3)],
        ["C", "B", "A"]),
    "H2 a correction takes A away from 50 and back": (
        [ev(1, "e1", "A", 50), ev(2, "e2", "B", 50), ev(3, "e3", "A", 10), ev(4, "u1", "A", 0, "UNDO", "e3")],
        ["B", "A", "C"]),
    "H3 A returns to 0, B and C never moved": (
        [ev(1, "e1", "A", 5), ev(2, "u1", "A", 0, "UNDO", "e1")],
        ["B", "C", "A"]),
}
 
EDGE_CASES = {
    "ADD +0 does not give a team a new time": (
        [ev(1, "e1", "A", 5), ev(2, "e2", "B", 5), ev(3, "e3", "A", 0)],
        ["A", "B", "C"]),
    "a waiting UNDO that cancels a late ADD changes nothing, so B keeps its time": (
        [ev(1, "e1", "B", 5), ev(2, "u1", "B", 0, "UNDO", "e9"), ev(3, "e2", "A", 5), ev(4, "e9", "B", 7)],
        ["B", "A", "C"]),
    "leaving a total with an ADD and coming back with another ADD also gets a new time": (
        [ev(1, "e1", "A", 10), ev(2, "e2", "B", 10), ev(3, "e3", "A", -4), ev(4, "e4", "A", 4)],
        ["B", "A", "C"]),
    "a negative team ranks below teams on 0": (
        [ev(1, "e1", "C", -20)],
        ["A", "B", "C"]),
    "no events: everyone on 0, team id decides": (
        [],
        ["A", "B", "C"]),
}
 
results = []
 
 
def check(name, condition):
    print(("PASS" if condition else "FAIL"), "-", name)
    results.append(condition)
 
 
print("=== 5a: three histories ===")
for name, (events, expected) in HISTORIES.items():
    by_rule = order(leaderboard_replay(events))
    naive = total_and_alphabet(events)
    print(f"\n{name}")
    print(f"   correct ranking (hand trace): {expected}")
    print(f"   replay solution:              {by_rule}")
    print(f"   incremental solution:         {order(incremental(events))}")
    print(f"   total + alphabet only:        {naive}")
    check(f"{name}: replay matches the hand trace", by_rule == expected)
    check(f"{name}: incremental matches the hand trace", order(incremental(events)) == expected)
    check(f"{name}: total + alphabet alone gives the WRONG ranking", naive != expected)
 
print("\n=== edge cases ===")
for name, (events, expected) in EDGE_CASES.items():
    check(f"{name}: replay", order(leaderboard_replay(events)) == expected)
    check(f"{name}: incremental", order(incremental(events)) == expected)
 
 
# ---------------------------------------------------------------- 5b: differential test
 
def random_history(rng, n):
    pool = [f"x{i}" for i in range(1, max(4, n // 2) + 1)]
    events = []
    for row in range(1, n + 1):
        roll = rng.random()
        if events and roll < 0.10:                 # an exact retry of an earlier event
            events.append(dict(rng.choice(events), row=row))
        elif roll < 0.65:                          # an ADD (the id may already exist: a conflict)
            events.append(ev(row, rng.choice(pool), rng.choice("ABC"), rng.randint(-5, 10)))
        else:                                      # an UNDO of any id, even one that has not arrived yet
            events.append(ev(row, rng.choice(pool), rng.choice("ABC"), 0, "UNDO", rng.choice(pool)))
    return events
 
 
def differential(rule, histories, seed):
    rng = random.Random(seed)
    prefixes = bad = 0
    first_bad = None
    for _ in range(histories):
        events = random_history(rng, rng.randint(1, 30))
        lb = IncrementalLeaderboard(rule=rule)
        for k, e in enumerate(events, start=1):
            lb.apply(e)
            prefixes += 1
            if lb.standings() != leaderboard_replay(events[:k], rule=rule):
                bad += 1
                first_bad = first_bad or events[:k]
    return prefixes, bad, first_bad
 
 
print("\n=== 5b: replay vs incremental on random histories ===")
for rule, label in (("return_gets_new_time", "rule from the brief"), (FIRST_EVER, "first-ever alternative")):
    prefixes, bad, first_bad = differential(rule, 3000, seed=2026)
    print(f"   {label}: 3000 histories, {prefixes} prefixes compared, {bad} disagreements")
    check(f"replay and incremental agree after every prefix ({label})", bad == 0)
    if first_bad:
        print("   first disagreeing history:", first_bad)
 
print()
print(f"{sum(results)}/{len(results)} passed")