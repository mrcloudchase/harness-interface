"""The environment anything Keeper starts runs in: the job's, minus every credential. Project code
(tests, checks, agents' work) never sees the GitHub token or a provider key; a live run is given
only the provider keys it names."""
from __future__ import annotations

import os

CREDENTIALS = {"KEEPER_SECRETS", "ACTIONS_ID_TOKEN_REQUEST_URL"}
SUFFIXES = ("_TOKEN", "_KEY", "_SECRET", "_PASSWORD")


def is_credential(name: str) -> bool:
    return name in CREDENTIALS or name.upper().endswith(SUFFIXES)


def clean(give: dict[str, str] | None = None) -> dict[str, str]:
    """os.environ without anything that looks like a credential, plus exactly `give`."""
    return {**{k: v for k, v in os.environ.items() if not is_credential(k)}, **(give or {})}
