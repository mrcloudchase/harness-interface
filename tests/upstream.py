"""A stand-in for a model provider: a TLS server on its own certificate that records every request it
gets and streams back a two-event answer. With `breaks` set, it corrupts the TLS stream after the
first event instead, the way a provider closing without close_notify looks to the gateway."""
import os
import socket
import ssl
import subprocess
import threading
from pathlib import Path

HEAD = b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: keep-alive\r\n\r\n"
FIRST, SECOND = b"data: one\n\n", b"data: two\n\n"


def certificate(directory: Path, ip: str) -> tuple[Path, Path]:
    """A self-signed certificate for `ip`, and its key."""
    cert, key = directory / "upstream.pem", directory / "upstream.key"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=upstream",
                    "-addext", f"subjectAltName=IP:{ip}", "-keyout", str(key), "-out", str(cert)],
                   check=True, capture_output=True)
    return cert, key


class Upstream:
    def __init__(self, directory: Path, ip: str = "127.0.0.1", bind: str = "127.0.0.1"):
        self.ca, key = certificate(directory, ip)
        self.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.tls.load_cert_chain(self.ca, key)
        self.listener = socket.create_server((bind, 0))
        self.port = self.listener.getsockname()[1]
        self.url = f"https://{ip}:{self.port}"
        self.requests: list[bytes] = []
        self.breaks = False
        self.first_seen = threading.Event()          # a client has the first event: now break, if breaking
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self) -> None:
        self.listener.close()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._answer, args=(conn,), daemon=True).start()

    def _answer(self, conn: socket.socket) -> None:
        try:
            with self.tls.wrap_socket(conn, server_side=True) as tls:
                data = b""
                while b"\r\n\r\n" not in data:
                    data += tls.recv(65536)
                head = data.split(b"\r\n\r\n", 1)[0].decode("latin-1").lower()
                length = next((int(line.split(":")[1]) for line in head.split("\r\n")
                               if line.startswith("content-length:")), 0)
                while len(data.split(b"\r\n\r\n", 1)[1]) < length:
                    data += tls.recv(65536)
                self.requests.append(data)
                tls.sendall(HEAD + FIRST)
                if self.breaks:
                    self.first_seen.wait(10)
                    os.write(tls.fileno(), b"\x17\x03\x03\x00\x20" + b"x" * 32)   # a TLS record no key opens
                    return
                tls.sendall(SECOND)
        except (OSError, ssl.SSLError):
            pass
