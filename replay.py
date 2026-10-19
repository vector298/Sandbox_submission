import json


def load_events(path="events.json"):
    with open(path) as f:
        return json.load(f)["transactions"]


def replay(events):
    """Rebuild the scores from scratch by walking the log from row 1 to the end."""
    scores = {"A": 0, "B": 0, "C": 0}
    seen = {}    
    active = {}  
    notes = []

    def details(event):
        return {k: v for k, v in event.items() if k != "row"}

    for e in events:
        row = f"row {e['row']:>2} | {e['id']}"

        
        if e["id"] in seen:
            first = seen[e["id"]]
            kind = "RETRY" if details(e) == first["details"] else "CONFLICT"
            notes.append(f"{row} | {kind} (first seen row {first['row']})")
            continue
        seen[e["id"]] = {"row": e["row"], "details": details(e)}

        if e["action"] == "ADD":
            scores[e["team"]] += e["points"]
            active[e["id"]] = {"team": e["team"], "points": e["points"]}

        elif e["action"] == "UNDO":
            target = e["refers_to"]
            if target in active:
                
                scores[active[target]["team"]] -= active[target]["points"]
                notes.append(f"{row} | UNDO applied to {target} "
                             f"(-{active[target]['points']} from team {active[target]['team']})")
                del active[target]
            else:
                notes.append(f"{row} | PENDING (target {target} not in force)")

    return scores, notes


if __name__ == "__main__":
    scores, notes = replay(load_events())
    for n in notes:
        print(n)
    print("Scores:", scores)