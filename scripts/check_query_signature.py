from qdrant_client import QdrantClient
import inspect

client = QdrantClient(host="localhost", port=6333)

print("Sig of query_points:")
print(inspect.signature(client.query_points))

print("Doc of query_points:")
print(client.query_points.__doc__)
