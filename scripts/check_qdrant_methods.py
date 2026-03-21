from qdrant_client import QdrantClient
import inspect

client = QdrantClient(host="localhost", port=6333)
print("\nType of client:", type(client))
print("\nDoes client have 'search'?", hasattr(client, 'search'))

print("\nMethods starting with 's':")
for m in dir(client):
    if m.startswith('s'):
        print(m)

print("\nMethods starting with 'q':")
for m in dir(client):
    if m.startswith('q'):
        print(m)

print("\nFull dir:")
print(dir(client))
