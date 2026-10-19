import json
from replay import load_events, replay
 
 
def ev(row, id, team, points, action, refers_to=None):
    return {"row": row, "id": id, "team": team, "points": points,
            "action": action, "refers_to": refers_to}
 
 
def by_row(outcomes):
    return {o["row"]: o for o in outcomes}
 
 
def check(name, condition):
    print(("PASS" if condition else "FAIL"), "-", name)
    return condition
 
 
results = []
 

scores, outcomes = replay(load_events())
with open("expected.json") as f:
    expected = json.load(f)["outcomes"]
 
results.append(check("real data: 13 rows in expected.json and 13 in the output",
                     len(expected) == len(outcomes) == 13))
for exp, got in zip(expected, outcomes):
    good = (exp["row"] == got["row"] and exp["outcome"] == got["outcome"]
            and (exp["reason"] is None or exp["reason"] == got["reason"]))
    results.append(check(f"row {exp['row']:>2} {exp['id']}: expected {exp['outcome']}, got {got['outcome']}", good))
 
results.append(check("real data: final scores are A=50 B=15 C=70", scores == {"A": 50, "B": 15, "C": 70}))
 

rows = by_row(outcomes)
results.append(check("snapshot: after row 1 scores are A=30 B=0 C=0",
                     rows[1]["scores_after"] == {"A": 30, "B": 0, "C": 0}))
results.append(check("snapshot: after row 12 scores are A=50 B=15 C=40",
                     rows[12]["scores_after"] == {"A": 50, "B": 15, "C": 40}))
 

s, o = replay([ev(1, "e1", "B", 20, "ADD"), ev(2, "u1", "C", 0, "UNDO", "e1")])
results.append(check("team mismatch: UNDO rejected, B keeps 20",
                     by_row(o)[2]["reason"] == "team mismatch" and s["B"] == 20))
 

s, o = replay([ev(1, "e1", "B", 20, "ADD"), ev(2, "u1", "B", 0, "UNDO", "e1"),
               ev(3, "u2", "B", 0, "UNDO", "e1")])
results.append(check("double UNDO: second one rejected as already undone, B = 0",
                     by_row(o)[3]["reason"] == "already undone" and s["B"] == 0))
 

s, o = replay([ev(1, "u1", "A", 0, "UNDO", "e9"), ev(2, "e9", "A", 10, "ADD")])
results.append(check("late target: pending UNDO applied when ADD arrives, A = 0",
                     by_row(o)[1]["outcome"] == "Accepted" and s["A"] == 0))
 

s, o = replay([ev(1, "u1", "C", 0, "UNDO", "e9"), ev(2, "e9", "A", 10, "ADD")])
results.append(check("late target, wrong team: UNDO rejected, A keeps 10",
                     by_row(o)[1]["reason"] == "team mismatch" and s["A"] == 10))
 

s, o = replay([ev(1, "u1", "A", 0, "UNDO", "e9")])
results.append(check("target never arrives: UNDO stays Pending",
                     by_row(o)[1]["outcome"] == "Pending"))
 

s, o = replay([ev(1, "e1", "B", 20, "ADD"), ev(2, "u1", "C", 0, "UNDO", "e1"),
               ev(3, "u2", "C", 0, "UNDO", "u1")])
results.append(check("undo of a rejected UNDO: rejected as target rejected",
                     by_row(o)[3]["reason"] == "target rejected"))
 

s, o = replay([ev(1, "e1", "B", 20, "ADD"), ev(2, "u1", "B", 0, "UNDO", "e1"),
               ev(3, "u2", "B", 0, "UNDO", "u1")])
results.append(check("undo of an accepted UNDO: rejected as not an ADD",
                     by_row(o)[3]["reason"] == "target not an ADD"))
 
s, o = replay(load_events("events_undo_first.json"))
rows = by_row(o)
results.append(check("undo first: final scores are A=50 B=15 C=70", s == {"A": 50, "B": 15, "C": 70}))
results.append(check("undo first: row 1 (UNDO e01) ends Accepted, applied once e01 arrived",
                     rows[1]["outcome"] == "Accepted" and "arrived later" in rows[1]["explanation"]))
results.append(check("undo first: row 1 keeps its own snapshot A=0 B=0 C=0",
                     rows[1]["scores_after"] == {"A": 0, "B": 0, "C": 0}))
results.append(check("undo first: row 2 (e01 arrives) shows A=0, the undo already applied",
                     rows[2]["scores_after"] == {"A": 0, "B": 0, "C": 0}))
results.append(check("undo first: every row has a scores_after snapshot",
                     all(r["scores_after"] is not None for r in o)))
results.append(check("undo first: e08 -> e99 still Pending (target never arrives)",
                     rows[11]["outcome"] == "Pending"))
 
print()
print(f"{sum(results)}/{len(results)} passed")