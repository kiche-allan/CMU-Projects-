#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bug 1 Crash Proof
=================
File:     rest_framework/authentication.py
Lines:    78-80
Function: BasicAuthentication.authenticate()

Bug:  Base64-decoded credentials that fail UTF-8 decoding are silently
      re-decoded as latin-1.  The wrong credential strings are passed to
      Django authenticate() with no error, no warning, and no log entry.
      py2 decoded with iso-8859-1 unconditionally -- consistent.
      py3 introduced a try/except that makes decoding non-deterministic.
"""

import base64
import io
import sys

# Force UTF-8 output so non-ASCII credential bytes print correctly on
# Windows consoles and when piped to Out-File.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SEP  = "=" * 72
SEP2 = "-" * 72

# ─────────────────────────────────────────────────────────────────────────────
# Verbatim from rest_framework/authentication.py lines 76-85
# (exceptions.AuthenticationFailed replaced with a plain exception subclass
#  so no Django import is needed)
# ─────────────────────────────────────────────────────────────────────────────

class AuthenticationFailed(Exception):
    pass


def decode_basic_credentials_buggy(raw_auth_bytes: bytes) -> tuple:
    """
    Verbatim DRF py3 logic -- authentication.py:76-85.
    raw_auth_bytes is the value of auth[1] (the base64 token after 'Basic ').
    Returns (userid, password) after decoding.
    """
    try:
        auth_decoded = base64.b64decode(raw_auth_bytes).decode('utf-8')
    except UnicodeDecodeError:
        auth_decoded = base64.b64decode(raw_auth_bytes).decode('latin-1')

    try:
        userid, password = auth_decoded.split(':', 1)
    except (TypeError, ValueError):
        raise AuthenticationFailed(
            'Invalid basic header. Credentials not correctly base64 encoded.'
        )
    return userid, password


def decode_basic_credentials_py2(raw_auth_bytes: bytes) -> tuple:
    """
    py2 (DRF 3.9.3) logic -- authentication.py:79-83.
    Decodes unconditionally with HTTP_HEADER_ENCODING = 'iso-8859-1'.
    Raises AuthenticationFailed if decode fails (it never does for iso-8859-1).
    """
    HTTP_HEADER_ENCODING = 'iso-8859-1'
    try:
        auth_decoded = base64.b64decode(raw_auth_bytes).decode(HTTP_HEADER_ENCODING)
    except (TypeError, UnicodeDecodeError, Exception):
        raise AuthenticationFailed(
            'Invalid basic header. Credentials not correctly base64 encoded.'
        )
    userid, password = auth_decoded.partition(':')[0], auth_decoded.partition(':')[2]
    return userid, password


def decode_basic_credentials_fixed(raw_auth_bytes: bytes) -> tuple:
    """
    Proposed fix: decode as UTF-8 strictly; raise on failure.
    No silent fallback.
    """
    try:
        auth_decoded = base64.b64decode(raw_auth_bytes).decode('utf-8')
    except UnicodeDecodeError:
        raise AuthenticationFailed(
            'Invalid basic header. Credentials contain non-UTF-8 bytes. '
            'Ensure your HTTP client encodes credentials as UTF-8.'
        )
    try:
        userid, password = auth_decoded.split(':', 1)
    except (TypeError, ValueError):
        raise AuthenticationFailed(
            'Invalid basic header. Credentials not correctly base64 encoded.'
        )
    return userid, password


def make_basic_token(raw_credential_bytes: bytes) -> bytes:
    """Base64-encode raw credential bytes, as an HTTP client would."""
    return base64.b64encode(raw_credential_bytes)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 -- Verbatim code at lines 78-80
# ─────────────────────────────────────────────────────────────────────────────

print(SEP)
print("SECTION 1 -- Verbatim DRF code at authentication.py lines 76-85")
print(SEP)
print("""
    # --- py3 (current, buggy) ---
    try:
        auth_decoded = base64.b64decode(auth[1]).decode('utf-8')     # line 78
    except UnicodeDecodeError:
        auth_decoded = base64.b64decode(auth[1]).decode('latin-1')   # line 80

    userid, password = auth_decoded.split(':', 1)                    # line 82


    # --- py2 (DRF 3.9.3, authentication.py:79-83) ---
    HTTP_HEADER_ENCODING = 'iso-8859-1'           # rest_framework/__init__.py:20
    try:
        auth_parts = base64.b64decode(auth[1]).decode(HTTP_HEADER_ENCODING)
    except (TypeError, UnicodeDecodeError, binascii.Error):
        raise AuthenticationFailed(...)           # propagates -- no fallback

    userid, password = auth_parts[0], auth_parts[2]

Key difference:
  py2 -- single unconditional decode with iso-8859-1. Consistent, deterministic.
  py3 -- try UTF-8, silently fall back to latin-1.  Non-deterministic for
         non-ASCII credentials. Identical bytes produce different strings
         depending on whether they happen to be valid UTF-8.
""")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 -- Credential where UTF-8 fails but latin-1 succeeds
# ─────────────────────────────────────────────────────────────────────────────

print(SEP)
print("SECTION 2 -- Credential where UTF-8 fails and latin-1 silently succeeds")
print(SEP)

# Bytes representing "admin:caf<0xe9>" -- latin-1 encoded password 'cafe' + e-acute.
# 0xe9 is 'e-acute' in latin-1/iso-8859-1 but NOT valid UTF-8 (it starts a
# 3-byte sequence with no continuation bytes).
latin1_credential = b"admin:caf\xe9"   # 'cafe' + latin-1 e-acute (e with acute accent)
token = make_basic_token(latin1_credential)

print(f"\nRaw credential bytes  : {latin1_credential!r}")
print(f"Base64 token          : {token!r}")

# Attempt UTF-8 decode directly
try:
    direct_utf8 = base64.b64decode(token).decode('utf-8')
    print(f"Direct UTF-8 decode   : OK => {direct_utf8!r}")
except UnicodeDecodeError as e:
    print(f"Direct UTF-8 decode   : FAILS -- {e}")

# py3 buggy path
userid_py3, password_py3 = decode_basic_credentials_buggy(token)
print(f"\npy3 buggy result:")
print(f"  userid   = {userid_py3!r}")
print(f"  password = {password_py3!r}  (came from latin-1 fallback -- no error raised)")
print(f"  Django authenticate() is called with these values silently")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 -- py2 behavior vs py3 behavior -- same bytes, different outcomes
# ─────────────────────────────────────────────────────────────────────────────

print()
print(SEP)
print("SECTION 3 -- py2 iso-8859-1 vs py3 UTF-8 fallback: same bytes, compare results")
print(SEP)

test_cases = [
    # (label, raw_bytes)
    ("ASCII-only credential (baseline)",
     b"admin:password"),

    ("Password with latin-1 byte 0xe9 (e-acute, invalid UTF-8)",
     b"admin:caf\xe9"),

    ("Password with UTF-8 encoded e-acute (0xc3 0xa9)",
     b"admin:caf\xc3\xa9"),

    ("Username with latin-1 byte, password clean",
     b"jos\xe9:secret"),

    ("Multiple non-ASCII latin-1 bytes",
     b"r\xe9sum\xe9:pass\xf6"),
]

print(f"\n{'Credential bytes':<35} {'py2 (iso-8859-1)':<22} {'py3 (utf-8+fallback)':<22} {'Match?'}")
print(SEP2)

for label, raw_cred in test_cases:
    token = make_basic_token(raw_cred)
    user_py2, pass_py2 = decode_basic_credentials_py2(token)
    user_py3, pass_py3 = decode_basic_credentials_buggy(token)

    py2_result = f"{user_py2!r}:{pass_py2!r}"
    py3_result = f"{user_py3!r}:{pass_py3!r}"
    match = "SAME" if (user_py2 == user_py3 and pass_py2 == pass_py3) else "DIFFERENT !"

    # Truncate long repr for display
    py2_disp = py2_result[:20] + "..." if len(py2_result) > 22 else py2_result
    py3_disp = py3_result[:20] + "..." if len(py3_result) > 22 else py3_result
    raw_disp = repr(raw_cred)[:33]

    print(f"  {raw_disp:<35} {py2_disp:<22} {py3_disp:<22} {match}")

print()
print("Explanation of DIFFERENT rows:")
print("  py2 treats ALL bytes as iso-8859-1 -- each byte maps to one latin-1 char.")
print("  py3 tries UTF-8 first. For valid UTF-8 multi-byte sequences (0xc3 0xa9),")
print("  py3 decodes them as a SINGLE unicode char (e-acute U+00E9).")
print("  py2 would see 0xc3 0xa9 as TWO latin-1 chars (U+00C3 U+00A9 = A-tilde + copyright).")
print("  A password set under py3 ('caf' + e-acute) may never authenticate under py2,")
print("  and a password hash stored under py2 conventions may never match under py3.")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 -- Security implication: two byte sequences authenticate as one user
# ─────────────────────────────────────────────────────────────────────────────

print()
print(SEP)
print("SECTION 4 -- Security: two different byte sequences decode to the same credential")
print(SEP)

# The same logical password 'e-acute' can be sent as:
#   A) latin-1 bytes: b'\xe9'  (1 byte, invalid UTF-8)
#   B) UTF-8 bytes:   b'\xc3\xa9' (2 bytes, valid UTF-8)
# Under py3's fallback, BOTH decode to the same unicode character U+00E9.

password_as_latin1_bytes = b"admin:caf\xe9"         # 1 byte for e-acute, invalid UTF-8
password_as_utf8_bytes   = b"admin:caf\xc3\xa9"     # 2 bytes for e-acute, valid UTF-8

token_latin1 = make_basic_token(password_as_latin1_bytes)
token_utf8   = make_basic_token(password_as_utf8_bytes)

user_a, pass_a = decode_basic_credentials_buggy(token_latin1)
user_b, pass_b = decode_basic_credentials_buggy(token_utf8)

print(f"\nScenario: user 'admin' sets password as unicode e-acute (U+00E9).")
print(f"  Django stores the hashed unicode string in its auth backend.")
print()
print(f"Client A sends latin-1 encoded credential (1 byte, 0xe9):")
print(f"  Raw bytes : {password_as_latin1_bytes!r}")
print(f"  Token     : {token_latin1!r}")
print(f"  Decoded   : userid={user_a!r}  password={pass_a!r}  (latin-1 fallback path)")
print()
print(f"Client B sends UTF-8 encoded credential (2 bytes, 0xc3 0xa9):")
print(f"  Raw bytes : {password_as_utf8_bytes!r}")
print(f"  Token     : {token_utf8!r}")
print(f"  Decoded   : userid={user_b!r}  password={pass_b!r}  (direct UTF-8 path)")
print()
print(f"Both credentials decode to the same password string: {pass_a!r} == {pass_b!r} => {pass_a == pass_b}")
print()
print("Result: two structurally DIFFERENT byte sequences in the Authorization header")
print("        both authenticate as the same user.  DRF accepts both representations.")
print("        A client that 'shouldn't' work (legacy, misconfigured, or attacker)")
print("        using latin-1 encoding will authenticate if the unicode password matches.")
print()

# Demonstrate the tokens are different
print(f"Token A : {token_latin1}")
print(f"Token B : {token_utf8}")
print(f"Tokens are identical: {token_latin1 == token_utf8}")
print("Two distinct Authorization headers => both authenticate => non-deterministic boundary.")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 -- latin-1 never fails: guaranteed catch-all
# ─────────────────────────────────────────────────────────────────────────────

print()
print(SEP)
print("SECTION 5 -- latin-1 never fails: accepts all 256 byte values")
print(SEP)

latin1_failures = 0
for byte_val in range(256):
    try:
        bytes([byte_val]).decode('latin-1')
    except Exception:
        latin1_failures += 1

utf8_failures = 0
for byte_val in range(256):
    try:
        bytes([byte_val]).decode('utf-8', errors='strict')
    except UnicodeDecodeError:
        utf8_failures += 1

print(f"\n  latin-1 failures decoding single bytes 0x00-0xff : {latin1_failures}/256")
print(f"  UTF-8   failures decoding single bytes 0x00-0xff : {utf8_failures}/256")
print()
print("  latin-1 is a complete bijection over all 256 byte values.")
print("  The except branch therefore ALWAYS succeeds -- it is an unconditional catch-all.")
print("  Every byte pattern that fails UTF-8 will silently produce a latin-1 string.")
print(f"  That is {utf8_failures} out of 256 possible byte values that silently bypass")
print("  the encoding check and reach Django's authenticate().")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 -- The fix: raise on UTF-8 failure, never substitute
# ─────────────────────────────────────────────────────────────────────────────

print()
print(SEP)
print("SECTION 6 -- Proposed fix: strict UTF-8, raise AuthenticationFailed on failure")
print(SEP)

print("""
Fixed implementation:

    def authenticate(self, request):
        ...
        try:
            auth_decoded = base64.b64decode(auth[1]).decode('utf-8')  # strict
        except (UnicodeDecodeError, binascii.Error):
            msg = _('Invalid basic header. Credentials must be UTF-8 encoded.')
            raise exceptions.AuthenticationFailed(msg)

        userid, password = auth_decoded.split(':', 1)
        ...

Why this is correct:
  RFC 7617 (2015) mandates UTF-8 for Basic Auth credentials.
  The py2 iso-8859-1 path was a legacy accommodation; it was NOT a security
  feature.  The py3 fallback silently accepts legacy clients that send
  non-UTF-8 bytes, masking misconfigured or potentially hostile clients.
  Raising instead means the client gets a 401 with a clear error message
  and must fix its encoding -- which is the correct outcome.
""")

print("Demonstrating fixed behavior:")
fix_cases = [
    ("ASCII credential",                   b"admin:password",     True),
    ("UTF-8 multi-byte password",          b"admin:caf\xc3\xa9",  True),
    ("latin-1 byte (invalid UTF-8)",       b"admin:caf\xe9",      False),
    ("Multiple latin-1 bytes",             b"r\xe9sum\xe9:pass",  False),
    ("Null byte in credential",            b"admin:\x00secret",   True),   # valid UTF-8
]

for label, raw_cred, should_pass in fix_cases:
    token = make_basic_token(raw_cred)
    try:
        user, pw = decode_basic_credentials_fixed(token)
        outcome = f"OK  => userid={user!r}  password={pw!r}"
    except AuthenticationFailed as e:
        outcome = f"AuthenticationFailed raised => {str(e)[:60]}"

    expected = "pass" if should_pass else "fail"
    print(f"  [{expected}] {repr(raw_cred):<35}  {outcome}")


# ─────────────────────────────────────────────────────────────────────────────
# CONCLUSION
# ─────────────────────────────────────────────────────────────────────────────

print()
print(SEP)
print("CONCLUSION")
print(SEP)
print(f"""
Bug:   BasicAuthentication decodes credentials as UTF-8 then falls back to
       latin-1 on UnicodeDecodeError.  latin-1 never raises, so all
       {utf8_failures} single-byte values that fail UTF-8 silently produce
       latin-1 strings that are passed to Django authenticate().

Effects:
  1. Non-determinism: same logical password encoded as latin-1 vs UTF-8
     produces the same unicode string under py3, meaning two different
     Authorization header values authenticate as the same user.

  2. py2/py3 behavioral divergence: a password set under py3 containing
     a properly UTF-8-encoded non-ASCII char (e.g. 0xc3 0xa9 for e-acute)
     would have decoded as TWO latin-1 characters under py2 (U+00C3, U+00A9).
     The py2->py3 migration silently changed which credentials are accepted.

  3. No signal: no exception, no warning, no log entry when the fallback
     fires.  Operations teams cannot detect that non-UTF-8 credentials are
     being accepted.

Root cause: py3 migration changed the unconditional iso-8859-1 decode
     (py2, consistent) to a try/except (py3, non-deterministic) without
     documenting the behavior change or adding observability.

Fix:  Decode strictly as UTF-8 per RFC 7617.  Raise AuthenticationFailed
     with a clear message if decoding fails.  Let the client fix its
     encoding rather than silently guessing.

Python version: {sys.version}
""")
