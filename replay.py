import json
 
 
def load_events(path="events.json"):
    with open(path) as f:
        return json.load(f)["transactions"]
 
 
def replay(events):
    """Rebuild scores and a per-row outcome by walking the log from row 1 to the end.
 
    Every row gets an outcome, a reason code, an explanation, and the A/B/C scores
    as they stood right after that row arrived.
 
    Time: events carry no timestamps, so arrival order stands in for time.
    A pending UNDO therefore waits until the end of the log (it never expires).
    """
    scores = {"A": 0, "B": 0, "C": 0}
    seen = {}         
    kinds = {}        
    active = {}       
    undone = set()    
    rejected = set()  
    pending = {}      
    outcomes = {}    
 
    def details(event):
        return {k: v for k, v in event.items() if k != "row"}
 
    def record(e, outcome, reason, explanation):
        old = outcomes.get(e["row"], {})          
        outcomes[e["row"]] = {"row": e["row"], "id": e["id"], "team": e["team"],
                               "outcome": outcome, "reason": reason,
                               "explanation": explanation,
                               "scores_after": old.get("scores_after")}  
 
    def reject_undo(e, reason, explanation):
        rejected.add(e["id"])
        record(e, "Rejected", reason, explanation)
 
    def apply_undo(e, late=False):
        """Decide an UNDO whose target has already been seen."""
        target = e["refers_to"]
        if target in rejected:
            reject_undo(e, "target rejected", f"{target} was itself rejected")
        elif kinds[target] != "ADD":
            reject_undo(e, "target not an ADD", f"{target} is not an ADD, so it cannot be undone")
        elif target in undone:
            reject_undo(e, "already undone", f"{target} was already undone")
        elif active[target]["team"] != e["team"]:
            reject_undo(e, "team mismatch",
                        f"team {e['team']} cannot undo {target}, which belongs to team {active[target]['team']}")
        else:
            team, points = active[target]["team"], active[target]["points"]
            scores[team] -= points
            undone.add(target)
            del active[target]
            when = " (target arrived later)" if late else ""
            record(e, "Accepted", None, f"UNDO applied{when}: reversed {target}, -{points} from team {team}")
 
    def handle(e):
       
        if e["id"] in seen:
            first = seen[e["id"]]
            if details(e) == first["details"]:
                record(e, "Retry", "duplicate", f"same as row {first['row']}, already processed")
            else:
                record(e, "Rejected", "conflict", f"same id as row {first['row']} but different details")
            return
        seen[e["id"]] = {"row": e["row"], "details": details(e)}
        kinds[e["id"]] = e["action"]
 
        if e["action"] == "ADD":
            scores[e["team"]] += e["points"]
            active[e["id"]] = {"team": e["team"], "points": e["points"]}
            record(e, "Accepted", None, f"ADD applied: {e['points']:+d} to team {e['team']}")
           
            for waiting in pending.pop(e["id"], []):
                apply_undo(waiting, late=True)
 
        elif e["action"] == "UNDO":
            target = e["refers_to"]
            if target in seen:
                apply_undo(e)
            else:
                pending.setdefault(target, []).append(e)
                record(e, "Pending", "target not seen", f"waiting for {target} to arrive")
 
    for e in events:
        handle(e)
       
        outcomes[e["row"]]["scores_after"] = dict(scores)
 
    return scores, list(outcomes.values())
 
 
def format_row(o):
    s = o["scores_after"]
    reason = o["reason"] or "-"
    return (f"row {o['row']:>2} | {o['id']} | team {o['team']} | {o['outcome']:<8} | {reason:<17} | "
            f"A={s['A']:>3} B={s['B']:>3} C={s['C']:>3} | {o['explanation']}")
 
 
if __name__ == "__main__":
    scores, outcomes = replay(load_events())
    for o in outcomes:
        print(format_row(o))
    print()
    print("Final scores:", scores)