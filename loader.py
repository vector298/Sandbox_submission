import json

with open("events.json") as f:
    events = json.load(f)["transactions"]

for e in events:
    print(f"row {e['row']:>2} | {e['id']} | team {e['team']} | {e['action']:<4} | {e['points']:>4}")