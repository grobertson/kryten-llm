
path = r"C:\Users\me\AppData\Local\pypoetry\Cache\virtualenvs\kryten-llm-QpOi9toT-py3.12\Lib\site-packages\kryten\client.py"
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()
    for i, line in enumerate(lines):
        if "def get_kv_bucket" in line:
            print(f"Found at line {i+1}: {line.strip()}")
