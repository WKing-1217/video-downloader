"""Honor Windows' enabled system proxy when unrelated *_PROXY flags exist."""
import os
import urllib.request


def windows_system_proxy():
    environment = urllib.request.getproxies_environment()
    # NODE_USE_ENV_PROXY becomes a bogus 'node_use_env' proxy in urllib. Its
    # presence must not suppress the real per-user Windows Internet Settings.
    if any(environment.get(key) for key in ("http", "https", "all")):
        return None  # yt-dlp already honors explicitly configured network proxies.
    if os.name != "nt":
        return None
    configured = urllib.request.getproxies_registry()
    return configured.get("https") or configured.get("http") or configured.get("all")
