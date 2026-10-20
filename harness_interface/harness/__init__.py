"""Layer 3: the harness contract. A folder (`HarnessFolder`), its cached install (`Installer`), where it
runs (`Placement`), how a response is prepared and what it returns (`prepare`, `collect`), and one
response on any runtime (`Response`). The only layer that knows what a harness is."""
from .contract import Request, Result, collect, prepare, session_token
from .folder import HarnessFolder, check_provider_url
from .install import InstallFailed, Installed, Installer
from .placement import Placement
from .response import Response

__all__ = ["HarnessFolder", "InstallFailed", "Installed", "Installer", "Placement", "Request", "Response", "Result",
           "check_provider_url", "collect", "prepare", "session_token"]
