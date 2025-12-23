
import asyncio
from kryten import KrytenClient

async def main():
    config = {
        "nats": {"servers": ["nats://localhost:4222"]},
        "channels": [{"domain": "test", "channel": "test"}],
        "service": {
            "name": "test",
            "version": "0.0.1",
            "enable_heartbeat": False,
            "enable_discovery": False
        }
    }
    client = KrytenClient(config)
    
    methods = [m for m in dir(client) if "kv" in m]
    print("KV methods on KrytenClient:")
    for m in methods:
        print(f" - {m}")

if __name__ == "__main__":
    asyncio.run(main())
