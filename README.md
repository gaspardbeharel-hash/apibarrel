# API Rotator Tool

A small Python script that rotates multiple API keys from a text file so they behave like one combined quota pool.

## Setup

1. Create a file named `api_keys.txt` next to this script.
2. Add one API key per line.
3. Empty lines and lines starting with `#` are ignored.

Example `api_keys.txt`:

```txt
# API keys are loaded in this file
key_1
key_2
key_3
```

## Run

```bash
python api_rotator.py
```

## How it works

The script loads all keys from `api_keys.txt`, then uses them in order:

1. Try the current API key.
2. If the API returns HTTP `429 Too Many Requests`, move to the next key.
3. Continue until all keys have been tried.
4. After the last key, loop back to the first one.

## Example usage

```python
from api_rotator import ApiRotator

rotator = ApiRotator("api_keys.txt")

response = rotator.request(
    "https://api.example.com/data",
    headers={"Accept": "application/json"},
)

print(response.json())
```

You can also call the proxy function directly:

```python
from api_rotator import request

response = request("https://api.example.com/data")
```

## Use from another project without changing its code

If the other project only accepts one API base URL or one API key placeholder, run the rotator as a local proxy and point that project to your local proxy URL.

Start the proxy:

```bash
python api_proxy.py --target https://api.example.com/v1 --keys-file api_keys.txt --listen 127.0.0.1:8080
```

Then use this as the project's API base URL:

```txt
http://127.0.0.1:8080
```

If the project asks for an API key anyway, put any non-empty placeholder value there, because the proxy will ignore the incoming `Authorization` header and replace it with the next key from `api_keys.txt`.

Example:

```txt
API_BASE_URL=http://127.0.0.1:8080
API_KEY=placeholder
```

The proxy forwards requests to:

```txt
https://api.example.com/v1/whatever/path
```

while rotating through your keys whenever the active key receives `429`.
