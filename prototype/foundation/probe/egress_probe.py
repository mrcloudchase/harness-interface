"""Where can this container go? Used at install time and at run time. Prints one JSON object."""
import json
import os
import socket
import ssl
import sys
import urllib.request
from urllib.parse import urlsplit


def connect(host, port=443):
    """CONNECT through $HTTPS_PROXY; the proxy's status line, or the error."""
    proxy = urlsplit(os.environ.get("HTTPS_PROXY", ""))
    if not proxy.hostname:
        return "no proxy"
    try:
        s = socket.create_connection((proxy.hostname, proxy.port), timeout=10)
        s.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
        line = s.recv(200).split(b"\r\n")[0].decode()
        s.close()
        return line.split(" ", 1)[1] if " " in line else line
    except OSError as e:
        return f"{type(e).__name__}"


def direct(host, port=443):
    try:
        socket.create_connection((host, port), timeout=5).close()
        return "open"
    except OSError as e:
        return f"{type(e).__name__}: {e}"[:80]


def loopback():
    """A server on 127.0.0.1 inside the container, reached with the proxy variables set."""
    import http.server
    import threading
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        return https_get(f"http://127.0.0.1:{srv.server_address[1]}/")
    finally:
        srv.shutdown()


def https_get(url, headers=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"[:120]


def main(hosts):
    out = {"connect": {h: connect(h) for h in hosts},
           "direct": {h: direct(h) for h in [*hosts[:2], "1.1.1.1", "172.17.0.1"]},
           "dns": {}, "env_has_provider_key": "HI_PROVIDER_KEY" in os.environ}
    out["loopback"] = loopback()
    for h in hosts[:2]:
        try:
            out["dns"][h] = socket.gethostbyname(h)
        except OSError as e:
            out["dns"][h] = type(e).__name__
    if os.environ.get("HI_PROVIDER_URL"):
        url = os.environ["HI_PROVIDER_URL"].rstrip("/") + "/v1/models"
        out["provider_no_key"] = https_get(url, {"anthropic-version": "2023-06-01"})
        out["provider_with_key"] = https_get(url, auth())
    return out


def auth():
    key = open(os.environ["HI_PROVIDER_KEY_FILE"]).read().strip() if os.environ.get("HI_PROVIDER_KEY_FILE") else ""
    if os.environ.get("HI_PROVIDER_API") == "anthropic-messages":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    return {"authorization": f"Bearer {key}"}


def stream(model):
    """One tiny streamed Messages call: proves SSE passes through the door unbuffered."""
    import time
    body = json.dumps({"model": model, "max_tokens": 40, "stream": True,
                       "messages": [{"role": "user", "content": "Count from 1 to 10, comma-separated."}]}).encode()
    req = urllib.request.Request(os.environ["HI_PROVIDER_URL"].rstrip("/") + "/v1/messages", data=body,
                                 headers={**auth(), "content-type": "application/json"})
    t0, times, text = time.time(), [], ""
    with urllib.request.urlopen(req, timeout=60) as r:
        for line in r:
            if line.startswith(b"data:"):
                times.append(round(time.time() - t0, 3))
                ev = json.loads(line[5:])
                text += ev.get("delta", {}).get("text", "")
    return {"events": len(times), "first_s": times[0], "last_s": times[-1], "text": text}


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1:])))
