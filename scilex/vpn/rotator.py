"""NordVPN IP rotation for bypassing per-IP API rate limits.

Works on native Windows, native Linux (nordvpn CLI), and WSL2 (calls NordVPN.exe
directly via the WSL2 interop path /mnt/c/Program Files/NordVPN/NordVPN.exe).
"""

import copy
import logging
import os
import platform
import random
import subprocess
import threading
import time
import urllib.request


class VPNRotator:
    """Controls NordVPN IP rotation to bypass per-IP rate limits.

    Configured via the ``collect.vpn`` section of ``scilex.yml``.  Use the
    module-level :func:`get_vpn_rotator` to obtain the shared singleton.
    """

    _WSL_EXE_PATHS = [
        "/mnt/c/Program Files/NordVPN/NordVPN.exe",
        "/mnt/c/Program Files (x86)/NordVPN/NordVPN.exe",
    ]
    _WIN_EXE_PATHS = [
        "C:/Program Files/NordVPN/NordVPN.exe",
        "C:/Program Files (x86)/NordVPN/NordVPN.exe",
    ]

    # All countries available on NordVPN (as of 2025)
    ALL_COUNTRIES = [
        "Albania",
        "Argentina",
        "Australia",
        "Austria",
        "Belgium",
        "Bosnia and Herzegovina",
        "Brazil",
        "Bulgaria",
        "Canada",
        "Chile",
        "Colombia",
        "Costa Rica",
        "Croatia",
        "Cyprus",
        "Czech Republic",
        "Denmark",
        "Estonia",
        "Finland",
        "France",
        "Georgia",
        "Germany",
        "Greece",
        "Hong Kong",
        "Hungary",
        "Iceland",
        "India",
        "Indonesia",
        "Ireland",
        "Israel",
        "Italy",
        "Japan",
        "Latvia",
        "Luxembourg",
        "Malaysia",
        "Mexico",
        "Moldova",
        "Netherlands",
        "New Zealand",
        "North Macedonia",
        "Norway",
        "Poland",
        "Portugal",
        "Romania",
        "Serbia",
        "Singapore",
        "Slovakia",
        "Slovenia",
        "South Africa",
        "South Korea",
        "Spain",
        "Sweden",
        "Switzerland",
        "Taiwan",
        "Thailand",
        "Turkey",
        "Ukraine",
        "United Arab Emirates",
        "United Kingdom",
        "United States",
        "Vietnam",
    ]

    def __init__(self, config: dict):
        self.enabled: bool = config.get("enabled", False)
        self.rotate_on: set = set(config.get("rotate_on_rate_limit", []))
        self.rotation_delay: int = int(config.get("rotation_delay", 15))
        self.max_rotations: int = int(config.get("max_rotations_per_session", 10))
        # countries: explicit list from config, or full list, or [] for quick-connect
        cfg_countries = config.get("countries", self.ALL_COUNTRIES)
        self.countries: list = cfg_countries if cfg_countries else []

        self._rotation_count = 0
        self._lock = threading.Lock()
        self._exe_path: str | None = None

        if self.enabled:
            self._exe_path = self._find_nordvpn_exe()
            if self._exe_path:
                apis_str = (
                    ", ".join(sorted(self.rotate_on)) if self.rotate_on else "all APIs"
                )
                logging.warning(
                    f"[VPN] Rotation enabled — exe: {self._exe_path} | "
                    f"APIs: {apis_str} | limit: {self.max_rotations} rotations/session"
                )
            else:
                logging.warning(
                    "[VPN] Rotation enabled in config but NordVPN.exe not found — disabling."
                )
                self.enabled = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_rotate(self, api_name: str) -> bool:
        """Return True if rotation is enabled for *api_name* and within limits."""
        if not self.enabled:
            return False
        if self.rotate_on and api_name not in self.rotate_on:
            return False
        if self._rotation_count >= self.max_rotations:
            logging.warning(
                f"[VPN] Session limit of {self.max_rotations} rotations reached — "
                f"no further rotation will be attempted."
            )
            return False
        return True

    def rotate(self) -> bool:
        """Disconnect then reconnect NordVPN and verify the IP changed.

        Thread-safe: only one rotation runs at a time even when multiple API
        threads hit a rate limit simultaneously.

        Returns:
            True if the public IP changed after rotation, False otherwise.
        """
        with self._lock:
            if not self._exe_path:
                return False

            rotation_n = self._rotation_count + 1
            old_ip = self._get_public_ip()
            logging.warning(
                f"[VPN] --- Starting rotation {rotation_n}/{self.max_rotations} "
                f"(current IP: {old_ip or 'unknown'}) ---"
            )

            try:
                logging.warning("[VPN] Disconnecting from current server...")
                disc_result = subprocess.run(
                    [self._exe_path, "-d"],
                    timeout=30,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if disc_result.returncode != 0 or disc_result.stderr.strip():
                    logging.warning(
                        f"[VPN] Disconnect exit={disc_result.returncode} "
                        f"stdout={disc_result.stdout.strip()!r} "
                        f"stderr={disc_result.stderr.strip()!r}"
                    )
                time.sleep(2)

                if self.countries:
                    country = random.choice(self.countries)
                    logging.warning(f"[VPN] Connecting to: {country}")
                    cmd = [self._exe_path, "-c", "-g", country]
                else:
                    logging.warning("[VPN] Connecting to new server (quick connect)...")
                    cmd = [self._exe_path, "-c"]
                conn_result = subprocess.run(
                    cmd, timeout=60, check=False, capture_output=True, text=True
                )
                if conn_result.returncode != 0 or conn_result.stderr.strip():
                    logging.warning(
                        f"[VPN] Connect exit={conn_result.returncode} "
                        f"stdout={conn_result.stdout.strip()!r} "
                        f"stderr={conn_result.stderr.strip()!r}"
                    )

                logging.warning(
                    f"[VPN] Connected — waiting {self.rotation_delay}s for IP to propagate"
                )
                time.sleep(self.rotation_delay)

                new_ip = self._get_public_ip()
                if new_ip and new_ip != old_ip:
                    self._rotation_count += 1
                    logging.warning(
                        f"[VPN] Rotation {self._rotation_count}/{self.max_rotations} complete: "
                        f"{old_ip} -> {new_ip}"
                    )
                    return True

                logging.warning(
                    f"[VPN] Rotation failed: IP unchanged after reconnect (still {new_ip})"
                )
                return False

            except Exception as e:
                logging.error(f"[VPN] Rotation error: {e}")
                return False

    @property
    def rotation_count(self) -> int:
        return self._rotation_count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_wsl2() -> bool:
        if platform.system() != "Linux":
            return False
        try:
            with open("/proc/version") as fh:
                return "microsoft" in fh.read().lower()
        except OSError:
            return False

    def _find_nordvpn_exe(self) -> str | None:
        candidates = self._WSL_EXE_PATHS if self._is_wsl2() else self._WIN_EXE_PATHS
        # Also allow native Linux nordvpn CLI
        if platform.system() == "Linux" and not self._is_wsl2():
            import shutil

            if shutil.which("nordvpn"):
                return "nordvpn"
        for p in candidates:
            if os.path.isfile(p):
                return p
        return None

    @staticmethod
    def _get_public_ip() -> str | None:
        for url in ("https://api64.ipify.org", "https://api4.ipify.org"):
            try:
                with urllib.request.urlopen(url, timeout=10) as resp:
                    return resp.read().decode().strip()
            except Exception:
                continue
        return None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: VPNRotator | None = None
_instance_config: dict | None = None
_instance_lock = threading.Lock()


def _normalize_vpn_config(vpn_config) -> dict:
    """Return ``vpn_config`` when it is a mapping, else an empty dict (disabled)."""
    return vpn_config if isinstance(vpn_config, dict) else {}


def get_vpn_rotator(vpn_config: dict | None = None) -> VPNRotator:
    """Return the shared VPNRotator for ``vpn_config`` (thread-safe, never raises).

    The singleton is rebuilt when the configuration differs from the one it was
    created with, so two jobs in one process (web API) each get their own
    settings. ``None`` or an empty mapping means rotation is disabled.

    Args:
        vpn_config: The ``vpn`` block of the resolved configuration.
    """
    global _instance, _instance_config
    config = _normalize_vpn_config(vpn_config)
    with _instance_lock:
        if _instance is None or config != _instance_config:
            try:
                _instance = VPNRotator(config)
            except Exception as error:
                logging.warning(f"VPN: invalid configuration ({error}) - disabled.")
                _instance = VPNRotator({})
                config = {}
            _instance_config = copy.deepcopy(config)
        return _instance


def vpn_config_from_configs(main_config, api_config=None) -> dict:
    """Return the VPN block of a resolved configuration, never raising.

    Reads ``main_config["vpn"]`` (``collect.vpn`` in ``scilex.yml``) and falls
    back to ``api_config["vpn"]`` for the legacy ``api.config.yml``. An empty
    dict disables rotation.
    """
    try:
        vpn_config = (main_config or {}).get("vpn") or (api_config or {}).get("vpn")
        return _normalize_vpn_config(vpn_config)
    except Exception as error:
        logging.debug(f"VPN: could not read config ({error}) - rotation disabled.")
        return {}


# ---------------------------------------------------------------------------
# Checks used by the desktop app (no rotation, no side effect)
# ---------------------------------------------------------------------------


def vpn_status() -> dict:
    """Describe the local NordVPN setup without changing the connection.

    Returns:
        ``{"exe_path": str | None, "public_ip": str | None, "platform": str}``:
        where the NordVPN client was found (None when it is not installed),
        the current public IP (None when offline) and the OS name.
    """
    probe = VPNRotator({})  # disabled: does not look for the client by itself
    return {
        "exe_path": probe._find_nordvpn_exe(),
        "public_ip": VPNRotator._get_public_ip(),
        "platform": "WSL2" if VPNRotator._is_wsl2() else platform.system(),
    }


def rotate_once(vpn_config: dict | None = None) -> tuple[bool, str | None, str | None]:
    """Rotate the NordVPN server once, as a collection would after a block.

    Uses a fresh rotator (the session cap of running collections is untouched).
    Briefly disconnects the VPN.

    Args:
        vpn_config: The ``vpn`` block (countries, rotation_delay); ``enabled``
            is forced on.

    Returns:
        ``(changed, ip_before, ip_after)``.
    """
    config = {**_normalize_vpn_config(vpn_config), "enabled": True}
    config["max_rotations_per_session"] = 1
    rotator = VPNRotator(config)
    before = VPNRotator._get_public_ip()
    if not rotator.enabled:
        return False, before, before
    changed = rotator.rotate()
    return changed, before, VPNRotator._get_public_ip()
