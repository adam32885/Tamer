"""Start of the Windows test exe. Copied as AsaApiLoader.exe it acts as the loader, otherwise as the server."""
import os, sys

if "loader" in os.path.basename(sys.executable).lower():
    import fake_loader  # noqa: F401
else:
    import fake_ark_server  # noqa: F401
