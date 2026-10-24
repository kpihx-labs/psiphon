"""Pinned upstream installation and private application state."""

import ctypes
import fcntl
import hashlib
import json
import os
import platform
import stat
import tempfile
from pathlib import Path

from psiphon import config

# Linux UAPI values: some portable CPython builds omit the symbolic constants.
F_ADD_SEALS = 1033
F_GET_SEALS = 1034
F_SEAL_SEAL = 0x01
F_SEAL_WRITE = 0x08
ENGINE_SEALS = 0x0F  # SEAL | SHRINK | GROW | WRITE


def snapshot_fd() -> int:
    """Use libc's named API when CPython was built without os.memfd_create."""
    create = getattr(ctypes.CDLL(None, use_errno=True), "memfd_create", None)
    if create is None:
        raise RuntimeError("memfd_create unavailable; refusing an unsealed engine")
    create.argtypes = (ctypes.c_char_p, ctypes.c_uint)
    create.restype = ctypes.c_int
    fd = create(b"psiphon-verified", 0x03)  # MFD_CLOEXEC | MFD_ALLOW_SEALING
    if fd < 0:
        raise OSError(ctypes.get_errno(), "Cannot create sealed engine snapshot")
    return fd


def private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise PermissionError(f"Refusing unowned or symlinked directory: {path}")
    path.chmod(0o700)


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    private_directory(path.parent)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
            temporary.chmod(mode)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def verify() -> None:
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        raise RuntimeError("Pinned engine supports Linux x86-64 only")
    if config.BINARY.is_symlink() or not config.BINARY.is_file():
        raise RuntimeError(f"Engine missing: {config.BINARY}; run psiphon setup")
    if digest(config.BINARY) != config.ENGINE_SHA256:
        raise RuntimeError("Engine SHA-256 mismatch; refusing execution")
    if not os.access(config.BINARY, os.X_OK):
        raise RuntimeError("Engine is not executable; run psiphon setup")


def setup() -> None:
    from psiphon import network

    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        raise RuntimeError("Pinned engine supports Linux x86-64 only")
    if digest(config.ENGINE_LICENSE) != config.ENGINE_LICENSE_SHA256:
        raise RuntimeError("Packaged upstream license SHA-256 mismatch")
    private_directory(config.ENGINE_DIR.parent)
    private_directory(config.ENGINE_DIR)
    if config.BINARY.is_symlink():
        raise PermissionError("Refusing a symlinked engine installation")
    if config.BINARY.exists() and digest(config.BINARY) == config.ENGINE_SHA256:
        config.BINARY.chmod(0o700)
    else:
        # Download into a private staging file; never execute an unchecked payload.
        with tempfile.NamedTemporaryFile(dir=config.ENGINE_DIR) as output:
            size = 0
            checksum = hashlib.sha256()
            with (
                network.session() as client,
                client.get(
                    config.ENGINE_URL, stream=True, timeout=(10, 30)
                ) as response,
            ):
                response.raise_for_status()
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > config.ENGINE_MAX_BYTES:
                        raise RuntimeError("Engine download exceeded size limit")
                    checksum.update(chunk)
                    output.write(chunk)
            if checksum.hexdigest() != config.ENGINE_SHA256:
                raise RuntimeError("Engine download SHA-256 mismatch; not installed")
            output.flush()
            os.fsync(output.fileno())
            # os.replace is atomic; the temporary file's context still closes it.
            staged = Path(output.name)
            staged.chmod(0o700)
            # Keep NamedTemporaryFile's cleanup path alive after the atomic copy.
            atomic_write(config.BINARY, staged.read_bytes(), 0o700)
    atomic_write(config.ENGINE_DIR / "LICENSE", config.ENGINE_LICENSE.read_bytes())
    verify()


def ensure_state() -> None:
    for path in (
        config.CONFIG_DIR,
        config.STATE_DIR,
        config.CACHE_DIR,
        config.DATA_DIR,
        config.RUNTIME_DIR,
    ):
        private_directory(path)


def write_config(region: str, proxy: bool) -> None:
    source = (
        config.ACTIVE_CONFIG if config.ACTIVE_CONFIG.exists() else config.BASE_CONFIG
    )
    payload = json.loads(source.read_text())
    payload.update(
        EgressRegion=region,
        LocalHttpProxyPort=config.HTTP_PROXY_PORT,
        LocalSocksProxyPort=config.SOCKS_PROXY_PORT,
        ListenInterface="",
        EmitDiagnosticNotices=True,
        DisableLocalHTTPProxy=not proxy,
        DisableLocalSocksProxy=not proxy,
        TunnelPoolSize=1,
        SplitTunnelOwnRegion=False,
        SplitTunnelRegions=[],
        UseUnixDomainSockets=False,
        PacketTunnelTransparentDNSIPv4Address=config.TRANSPARENT_DNS,
        PacketTunnelTransparentDNSIPv6Address="",
    )
    atomic_write(config.ACTIVE_CONFIG, json.dumps(payload, indent=2).encode())


def command(interface: str | None = None) -> list[str]:
    result = [
        str(config.BINARY),
        "-config",
        str(config.ACTIVE_CONFIG),
        "-dataRootDirectory",
        str(config.DATA_DIR),
    ]
    if interface:
        result += [
            "-tunDevice",
            config.TUN_NAME,
            "-tunBindInterface",
            interface,
            "-tunDNSServers",
            config.BYPASS_DNS,
        ]
    return result


def open_user_path(
    path: str, uid: int, flags: int = os.O_RDONLY, strict: bool = False
) -> int:
    """Open anchored components, refusing symlinks and foreign-owned ancestors.

    Root may traverse root-owned directories, and sticky root-owned /tmp. The
    final file/directory must belong to the caller and not be writable by others.
    Engine strict mode also rejects writable ancestors. State ancestors may have
    normal shared-group permissions: only the unprivileged engine consumes state.
    No root-side writes, truncation or creation occur while validating a path.
    """
    location = Path(path)
    if not location.is_absolute() or ".." in location.parts or location == Path("/"):
        raise PermissionError("Expected an absolute caller-owned path")
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in location.parts[1:-1]:
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent,
            )
            try:
                info = os.fstat(child)
                sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
                if info.st_uid not in (0, uid) or (
                    strict and info.st_mode & 0o022 and not sticky_root
                ):
                    raise PermissionError("Unsafe path ancestor")
            except BaseException:
                os.close(child)
                raise
            os.close(parent)
            parent = child
        fd = os.open(
            location.name,
            flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=parent,
        )
        try:
            info = os.fstat(fd)
            expected_type = stat.S_ISDIR if flags & os.O_DIRECTORY else stat.S_ISREG
            if (
                info.st_uid != uid
                or info.st_mode & 0o022
                or not expected_type(info.st_mode)
            ):
                raise PermissionError(
                    "Expected a caller-owned, non-writable-by-others path"
                )
        except BaseException:
            os.close(fd)
            raise
        return fd
    finally:
        os.close(parent)


def sealed_engine(path: str, uid: int) -> int:
    """Privileged-side verification of a sealed snapshot, never a requested hash.

    Copying to a sealed memfd prevents a user-writable XDG executable being changed
    between hash verification and exec. The returned descriptor must be closed.
    """
    source = open_user_path(path, uid, strict=True)
    snapshot = -1
    try:
        info = os.fstat(source)
        if not info.st_mode & stat.S_IXUSR or info.st_size > config.ENGINE_MAX_BYTES:
            raise PermissionError("Invalid engine mode or size")
        snapshot = snapshot_fd()
        checksum = hashlib.sha256()
        size = 0
        while chunk := os.read(source, 65536):
            size += len(chunk)
            if size > config.ENGINE_MAX_BYTES:
                raise RuntimeError("Engine snapshot exceeded size limit")
            checksum.update(chunk)
            data = memoryview(chunk)
            while data:
                count = os.write(snapshot, data)
                data = data[count:]
        if checksum.hexdigest() != config.ENGINE_SHA256:
            raise RuntimeError("Elevated engine SHA-256 mismatch; refusing execution")
        os.fchmod(snapshot, 0o555)
        fcntl.fcntl(snapshot, F_ADD_SEALS, ENGINE_SEALS)
        os.lseek(snapshot, 0, os.SEEK_SET)
        return snapshot
    except BaseException:
        if snapshot >= 0:
            os.close(snapshot)
        raise
    finally:
        os.close(source)
