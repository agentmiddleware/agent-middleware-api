"""QA-only guard inherited by Python child processes; never used by product."""
import ipaddress
import os
import socket
import sys

# Suppress all dotenv I/O before importing app settings.
from pydantic_settings.sources import DotEnvSettingsSource
DotEnvSettingsSource._read_env_files = lambda self: {}
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
dotenv.dotenv_values = lambda *args, **kwargs: {}

def local(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

def numeric_address(host):
    # inet_aton parses legacy numeric IPv4 spellings without DNS or I/O.
    # Existing SSRF tests deliberately ask getaddrinfo to classify these.
    try:
        socket.inet_aton(host)
        return True
    except (OSError, TypeError):
        return False


def guard(event, args):
    if event in ("socket.connect", "socket.sendto"):
        address = args[1]
        if isinstance(address, tuple) and not local(address[0]):
            raise PermissionError("QA guard: non-loopback network denied")
    if event == "socket.getaddrinfo" and args[0] is not None and not local(args[0]) and not numeric_address(args[0]):
        raise PermissionError("QA guard: external DNS denied")
    if event == "subprocess.Popen":
        executable = os.path.basename(str(args[0]))
        if executable in {"railway", "vercel", "fly", "supabase", "firebase", "curl", "wget"}:
            raise PermissionError("QA guard: external command denied")
    if event == "open" and isinstance(args[0], (str, bytes)):
        name = os.path.basename(os.fsdecode(args[0]))
        if name == ".env" or name.startswith(".env."):
            raise PermissionError("QA guard: environment file access denied")

sys.addaudithook(guard)
