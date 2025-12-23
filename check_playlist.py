#!/usr/bin/env python
"""Quick script to check playlist structure in KV store."""
import asyncio
import json
from kryten import KrytenClient

async def main():
    config = {
        'nats': {'servers': ['nats://localhost:4222']},
        'channels': [{'domain': 'cytu.be', 'channel': '420grindhouse'}]
    }
    client = KrytenClient(config)
    await client.connect()
    
    # Get playlist
    items = await client.kv_get("kryten_420grindhouse_playlist", "items", default=[], parse_json=True)
    print(f"Total: {len(items)} items")
    print("\nFirst 3 items:")
    for i, item in enumerate(items[:3]):
        print(f"\n  [{i}] Full item: {json.dumps(item, indent=4)[:500]}...")
    
    # Check if there's a current_media key
    current = await client.kv_get("kryten_420grindhouse_playlist", "current", default=None, parse_json=True)
    print(f"\n\ncurrent_media key: {current}")
    
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
