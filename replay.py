import json

with open("events.json") as f:
    events = json.load(f)["transactions"]

scores = {"A": 0, "B": 0, "C": 0}
seen = {}  # event id -> details of the first event that arrived with that id


def details(event):
    """Everything about the event except its position in the log."""
    return {k: v for k, v in event.items() if k != "row"}


for e in events:
    if e["id"] in seen:
        if details(e) == seen[e["id"]]["details"]:
            print(f"row {e['row']:>2} | {e['id']} | RETRY    (same as row {seen[e['id']]['row']})")
        else:
            print(f"row {e['row']:>2} | {e['id']} | CONFLICT (differs from row {seen[e['id']]['row']})")
        continue

    seen[e["id"]] = {"row": e["row"], "details": details(e)}

    if e["action"] == "ADD":
        scores[e["team"]] += e["points"]

print()
print("Scores:", scores)