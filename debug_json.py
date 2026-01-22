import json
import sys

path = r"c:\Users\eripc\OneDrive\Desktop\workspace\cobol-rekt\out\report\test-exp.cbl.report\unified_model\test-exp.cbl-unified.json"
target_id = "e816e151-dc80-41c8-907c-189c6d7c3b6b"

with open(path, 'r') as f:
    data = json.load(f)

print(f"Root keys: {list(data.keys())}")

nodes = data.get("codeVertices", [])
print(f"Total codeVertices: {len(nodes)}")

found = False
for n in nodes:
    if n["id"] == target_id:
        print("Found target ID in codeVertices!")
        print(json.dumps(n, indent=2))
        found = True
        break

if not found:
    print("Target ID NOT found in codeVertices.")

# Check edges
edges = data.get("edges", [])
print(f"Total edges: {len(edges)}")
count = 0
for e in edges:
    if e["toNodeID"] == target_id:
        count += 1
print(f"Edges pointing to target ID: {count}")
