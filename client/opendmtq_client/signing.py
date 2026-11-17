"""The OpenDMTQ project's signature on its releases: an Ed25519 signature over each release's checksums file.

Every release has opendmtq-<version>-sha256sums.txt, the SHA-256 of each of its other files, and beside it
opendmtq-<version>-sha256sums.txt.sig, the project's signature over that file's bytes: 64 bytes, Ed25519 as RFC 8032
defines it, by the key whose public half is built in here. Whoever hands a release's file on (a server handing the PC
client's updates to its launchers over plain HTTP, a mirror, a disk carried to a closed network) can change the file
and the checksums beside it, but not the signature: what checks out against the signed checksums is the project's.

The PC client's update feed (releases.win.json) is one of the files summed, so what it says is signed as well: the
packages' names, sizes and hashes, and for the full package FilesSHA256, the SHA-256 of the files it holds by their
names (files_sha256). A package Velopack puts together from a delta package holds the same files zipped again, so its
bytes are not the signed ones and it is checked by its files.

The same module is in the server's tools (tools/opendmtq_tools/signing.py) and in the PC client's launcher
(client/opendmtq_client/signing.py), byte for byte (a check of the repository's says so): neither has a cryptography
library to lean on, so it is plain Python, a check taking a few hundredths of a second.

A build for a test also takes the public keys written into update-test-keys.txt beside this module, one a line: the
tests sign their made-up releases with a key made for the run and thrown away after it, never with the project's. A
release's copy has no such file, or an empty one (.github/release_assets.py checks the PC client's package).

  python3 signing.py new-key KEY_FILE          make a signing key (kept off the repository), print its public key
  python3 signing.py sign KEY_FILE SUMS...     write SUMS.sig beside each checksums file
  python3 signing.py check [--key HEX] SUMS... check each SUMS.sig against the keys built in (and HEX)
"""

import hashlib
import os
import re
import sys
import zipfile

# The public keys a signature is taken from (hex). The signing key itself stays on the machine that makes the
# releases, off the repository; a new key is added here before it signs anything, so that what is out there goes on
# taking the releases it signs.
KEYS = ("8ead95551a5d5d216dca12de20138465d4cfbcec48ec2b2611c9e49fc47b77d7",)
# The public keys a test build takes besides: one a line, written beside this module by a test, never by a release.
TEST_KEYS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "update-test-keys.txt")
# A public key as it is written: 32 bytes in hex.
KEY_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
# What a signature is: 64 bytes, as a file of its own beside the checksums file.
SIG_SIZE = 64
SIG_SUFFIX = ".sig"
# A release's checksums file: its name says the version, every line a file of the release.
SUMS_NAME = "opendmtq-{version}-sha256sums.txt"
# The largest checksums file taken as one: a few lines of a hundred characters; anything far larger is no such file.
SUMS_LIMIT = 64 * 1024
# A line of it, as sha256sum writes it: the hash, two spaces, the file's name.
SUMS_LINE = re.compile(r"^([0-9a-f]{64})  ([^/\\\s][^/\\]*)$")

# ---- Ed25519 (RFC 8032, section 5.1), on points in extended coordinates (X, Y, Z, T): x = X/Z, y = Y/Z, xy = T/Z
# The field's prime.
_P = 2 ** 255 - 19
# The order of the base point.
_L = 2 ** 252 + 27742317777372353535851937790883648493
# The curve's constant d = -121665/121666.
_D = -121665 * pow(121666, _P - 2, _P) % _P
# A square root of -1, for recovering x from y.
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _add(a, b):
    """The sum of two points (the formula is complete: it also doubles a point added to itself)."""
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    # RFC 8032's addition for twisted Edwards curves with a = -1, step for step.
    pa = (y1 - x1) * (y2 - x2) % _P
    pb = (y1 + x1) * (y2 + x2) % _P
    pc = t1 * 2 * _D * t2 % _P
    pd = z1 * 2 * z2 % _P
    e, f, g, h = pb - pa, pd - pc, pd + pc, pb + pa
    return e * f % _P, g * h % _P, f * g % _P, e * h % _P


def _times(n, point):
    """n times a point, by doubling and adding (n is never secret where this runs as a check; a signing run is on
    the release machine alone)."""
    out = (0, 1, 1, 0)
    while n > 0:
        # Each bit of n adds the point doubled so far.
        if n & 1:
            out = _add(out, point)
        point = _add(point, point)
        n >>= 1
    return out


def _same(a, b):
    """True when two points in extended coordinates are the same point (x and y equal once divided by Z)."""
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _x_from(y, sign):
    """The x of the point with this y and x's lowest bit, or None when there is no such point."""
    if y >= _P:
        # Not a field element: no point is written that way.
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        # x is 0, which has no lowest bit set: a sign of 1 names no point.
        return None if sign else 0
    # A square root by the prime's form (p = 5 mod 8), then the other root when that one squares to -x2.
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        # No square root at all: no point has this y.
        return None
    return _P - x if (x & 1) != sign else x


def _encode(point):
    """A point as 32 bytes: y, little-endian, with x's lowest bit in the top bit."""
    zi = pow(point[2], _P - 2, _P)
    x, y = point[0] * zi % _P, point[1] * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decode(data):
    """The point 32 bytes stand for, or None when they stand for none."""
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    # The top bit is x's lowest one; the rest is y.
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _x_from(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


# The base point: y = 4/5, with an even x.
_BY = 4 * pow(5, _P - 2, _P) % _P
_B = (_x_from(_BY, 0), _BY, 1, _x_from(_BY, 0) * _BY % _P)


def _sha512_int(*parts):
    """SHA-512 of the parts joined, as a little-endian number (RFC 8032's H)."""
    return int.from_bytes(hashlib.sha512(b"".join(parts)).digest(), "little")


def _expand(seed):
    """The secret scalar and the nonce prefix a 32-byte seed stands for."""
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    # The scalar's fixed bits (RFC 8032, 5.1.5): a multiple of 8, with bit 254 set.
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed):
    """The 32-byte public key of a 32-byte seed."""
    return _encode(_times(_expand(seed)[0], _B))


def sign(seed, message):
    """The 64-byte signature of a message with a 32-byte seed."""
    a, prefix = _expand(seed)
    public = _encode(_times(a, _B))
    # The nonce comes from the seed and the message: the same message signed twice gives the same signature.
    r = _sha512_int(prefix, message) % _L
    big_r = _encode(_times(r, _B))
    k = _sha512_int(big_r, public, message) % _L
    return big_r + ((r + k * a) % _L).to_bytes(32, "little")


def verify(public, message, signature):
    """True when the signature is the holder of this public key's signature of the message."""
    if len(public) != 32 or len(signature) != SIG_SIZE:
        return False
    point_a, point_r = _decode(public), _decode(signature[:32])
    if point_a is None or point_r is None:
        # Bytes that name no point on the curve: no signature of anyone's.
        return False
    s = int.from_bytes(signature[32:], "little")
    # A signature's s is below the order; a larger one is another spelling of the same signature.
    if s >= _L:
        return False
    k = _sha512_int(signature[:32], public, message) % _L
    # The check of RFC 8032, 5.1.7: [s]B = R + [k]A.
    return _same(_times(s, _B), _add(point_r, _times(k, point_a)))


# ---- the keys taken
def added_keys(path=None):
    """The public keys a test build wrote in (TEST_KEYS_FILE), in lower case; none without the file, with an empty one
    (a release's), or with one that cannot be read. A line that is no key is left out, never taken for one."""
    try:
        with open(path or TEST_KEYS_FILE, encoding="ascii") as f:
            # Split on any white space: one key a line, the last with or without its newline.
            words = f.read().split()
    except (OSError, ValueError):
        # No such file (a release, a copy of the repository), or bytes that are no text: no keys besides the project's.
        return ()
    return tuple(word.lower() for word in words if KEY_HEX.match(word))


def trusted():
    """Every public key a signature is taken from: the project's (KEYS), then a test build's own. Read at each check,
    so that a test which puts its own key in KEYS is checked against that key."""
    return tuple(KEYS) + added_keys()


def signed_by(data, signature, keys=None):
    """The public key (hex) whose holder signed these bytes, among `keys` (the ones taken, trusted(), unless others are
    given), or None when none did."""
    keys = trusted() if keys is None else keys
    if not isinstance(signature, (bytes, bytearray)) or len(signature) != SIG_SIZE:
        # Not a signature at all (a page instead of the file, a file cut short).
        return None
    for key in keys:
        if verify(bytes.fromhex(key), bytes(data), bytes(signature)):
            return key
    return None


# ---- a release's checksums
class Unsigned(Exception):
    """What a release's file was refused for: its checksums are not signed by a key taken, they name no such file, or
    the file is not the one they name. Its words say which and are shown as they are (the log, the admin pages)."""


def sums_name(version):
    """The checksums file's name for a version: opendmtq-1.2.3-sha256sums.txt."""
    return SUMS_NAME.format(version=version)


def read_sums(text):
    """{file name: SHA-256} of a checksums file's text, as sha256sum writes it. Unsigned for anything else: a line
    that is not a hash and a plain file name, a name twice, no line at all."""
    sums = {}
    for line in text.splitlines():
        found = SUMS_LINE.match(line)
        if not found:
            raise Unsigned("the checksums file has a line that is no file's checksum: %r" % line[:80])
        digest, name = found.groups()
        if name in sums:
            # Two hashes for one name: which one would be meant is not for this code to choose.
            raise Unsigned("the checksums file names %s twice" % name)
        sums[name] = digest
    if not sums:
        raise Unsigned("the checksums file names no file")
    return sums


def check_sums(data, signature, version, keys=None):
    """{file name: SHA-256} of the release `version`'s checksums file, once its bytes (`data`) check out against the
    signature beside it (`signature`, bytes) by a key taken. Unsigned, with why, when they do not, or when the file
    does not name the version in each of the release's files that has one in its name."""
    if not isinstance(data, (bytes, bytearray)) or len(data) > SUMS_LIMIT:
        raise Unsigned("%s is not a release's checksums file" % sums_name(version))
    if signed_by(data, signature, keys) is None:
        raise Unsigned("%s is not signed by the OpenDMTQ project" % sums_name(version))
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        raise Unsigned("%s is not text" % sums_name(version)) from None
    sums = read_sums(text)
    # The version in each name that has one: the signed checksums of another release do not pass for this one's.
    for name in sums:
        if re.search(r"-\d+\.\d+\.\d+", name) and ("-%s-" % version) not in name:
            raise Unsigned("%s names %s, of another version" % (sums_name(version), name))
    return sums


def sha256_of(path):
    """The SHA-256 of a file, read a megabyte at a time (packages and installers are tens of megabytes)."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for piece in iter(lambda: f.read(1 << 20), b""):
            digest.update(piece)
    return digest.hexdigest()


def check_file(sums, name, path):
    """Nothing when the file at `path` is the release's file `name` as the signed checksums (`sums`, check_sums())
    give it; Unsigned, with why, when the checksums name no such file or give it another SHA-256."""
    want = sums.get(name)
    if want is None:
        raise Unsigned("the release's signed checksums name no %s" % name)
    if sha256_of(path) != want:
        raise Unsigned("%s is not the file the release signed" % name)


def files_sha256(path):
    """The SHA-256 of what a zip holds, whatever zipped it: a line for every file in it (its name with forward slashes,
    a zero byte, the SHA-256 of its bytes, a newline), in the order of the names. None for a file that is not a zip.

    A package Velopack puts together from a delta package holds the same files as the one the release built (each
    patched to the same bytes), zipped again in another order and with another compression."""
    try:
        with zipfile.ZipFile(path) as archive:
            lines = []
            for info in archive.infolist():
                if info.is_dir():
                    # A folder's own entry holds nothing (one zip writer lists them, another does not).
                    continue
                digest = hashlib.sha256()
                with archive.open(info) as f:
                    for piece in iter(lambda: f.read(1 << 20), b""):
                        digest.update(piece)
                lines.append("%s\0%s\n" % (info.filename.replace("\\", "/"), digest.hexdigest()))
    except (zipfile.BadZipFile, OSError, ValueError, EOFError, NotImplementedError):
        # Not a zip, one cut short, or one with a compression this Python cannot read: nothing to check by its files.
        return None
    return hashlib.sha256("".join(sorted(lines)).encode("utf-8")).hexdigest()


def pem(key_hex):
    """A public key as PEM (SubjectPublicKeyInfo), for whoever checks a release with OpenSSL instead of this module:
    openssl pkeyutl -verify -pubin -inkey key.pem -rawin -in SUMS -sigfile SUMS.sig."""
    import base64
    # The DER head of an Ed25519 public key (RFC 8410), then the key's 32 bytes.
    der = bytes.fromhex("302a300506032b6570032100") + bytes.fromhex(key_hex)
    return "-----BEGIN PUBLIC KEY-----\n%s\n-----END PUBLIC KEY-----\n" % base64.b64encode(der).decode("ascii")


def _read_seed(path):
    """The 32-byte seed in a key file (64 hex digits); stops with why for anything else."""
    with open(path, encoding="ascii") as f:
        seed = bytes.fromhex(f.read().strip())
    if len(seed) != 32:
        raise SystemExit("%s is not a signing key (64 hex digits)" % path)
    return seed


def sign_file(key_file, path):
    """Write path.sig, the signature of the file's bytes with the key in `key_file`; returns the public key (hex)."""
    seed = _read_seed(key_file)
    with open(path, "rb") as f:
        data = f.read()
    # Written beside it whole, then put in its place: a signature is never half there.
    part = path + SIG_SUFFIX + ".part"
    with open(part, "wb") as f:
        f.write(sign(seed, data))
    os.replace(part, path + SIG_SUFFIX)
    return public_key(seed).hex()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "new-key":
        if os.path.exists(argv[1]):
            raise SystemExit("%s exists; a signing key is never written over" % argv[1])
        seed = os.urandom(32)
        # Readable by its owner only, from the moment it exists.
        fd = os.open(argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(seed.hex() + "\n")
        print(public_key(seed).hex())
        return 0
    if len(argv) >= 3 and argv[0] == "sign":
        for path in argv[2:]:
            key = sign_file(argv[1], path)
            print("signed %s with the key %s" % (os.path.basename(path), key))
        return 0
    if len(argv) >= 2 and argv[0] == "check":
        paths, keys = argv[1:], trusted()
        # --key HEX, before the files: a test's key, taken besides the ones built in.
        while len(paths) >= 2 and paths[0] == "--key":
            if not KEY_HEX.match(paths[1]):
                raise SystemExit("%s is not a public key (64 hex digits)" % paths[1])
            keys, paths = keys + (paths[1].lower(),), paths[2:]
        if not paths:
            # A key and no file: nothing was checked, which must not read as a pass.
            raise SystemExit("no checksums file to check")
        bad = 0
        for path in paths:
            try:
                with open(path, "rb") as f:
                    data = f.read(SUMS_LIMIT + 1)
                with open(path + SIG_SUFFIX, "rb") as f:
                    signature = f.read(SIG_SIZE + 1)
                key = signed_by(data, signature, keys)
            except OSError:
                key = None
            print("%s: %s" % (os.path.basename(path), "signed by %s" % key if key else "NOT SIGNED by a key taken"))
            bad += key is None
        return 1 if bad else 0
    # Anything else: the three commands, as the module's description gives them.
    print("\n".join(__doc__.strip().splitlines()[-3:]))
    return 2


if __name__ == "__main__":
    sys.exit(main())
