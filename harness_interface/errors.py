"""Requests the server refuses, and the HTTP status each refusal answers with. Anything else that
goes wrong is a bug, and stays a 500."""


class ClientError(Exception):
    status = 400


class Conflict(ClientError):
    status = 409
