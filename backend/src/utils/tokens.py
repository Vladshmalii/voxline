"""The HMAC a provider-facing URL carries, so any process can verify it.

The hooks service answers webhooks for calls and messages it has no state
about — the call is running in a different process, the message was sent by
the API minutes ago. Rather than a lookup per request, the URL itself carries
proof: an HMAC of the row's uuid under the service secret. Stateless to
verify, nothing an attacker can enumerate produces a valid one, and any
replica can answer for any row.

It is not a substitute for a carrier's own signature where one exists — the
token authenticates the *URL*, not the parameters posted to it, so a captured
URL replayed with rewritten fields still passes here. See
:mod:`src.utils.twilio` for the half that covers the body.

Pure functions, no project imports, per the ``utils/`` rules.
"""

from __future__ import annotations

import hashlib
import hmac

#: Hex characters kept from the digest. 128 bits is far past guessable and
#: keeps the URLs a human can read in a log.
_LENGTH = 32


def mint(secret: str, subject: str) -> str:
    """The token a URL addressing `subject` must carry."""
    return hmac.new(secret.encode(), subject.encode(), hashlib.sha256).hexdigest()[
        :_LENGTH
    ]


def verify(secret: str, subject: str, token: str | None) -> bool:
    """Constant-time check of a presented token."""
    if not token:
        return False
    return hmac.compare_digest(mint(secret, subject), token)
