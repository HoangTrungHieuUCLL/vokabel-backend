"""Generate the VAPID key pair for web push.

    python scripts/generate_vapid_keys.py

Put VAPID_PRIVATE_KEY in the backend's environment only. VAPID_PUBLIC_KEY goes
in the backend too -- the frontend fetches it from /notifications/vapid-key
rather than baking it into the bundle, so rotating the pair does not need a
frontend redeploy.

Rotating the keys invalidates every existing subscription: each device has to
re-enable notifications.
"""

import base64

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main() -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_raw = private_key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = private_key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)

    print(f"VAPID_PRIVATE_KEY={b64(private_raw)}")
    print(f"VAPID_PUBLIC_KEY={b64(public_raw)}")
    print("VAPID_SUBJECT=mailto:you@example.com  # change to your address")


if __name__ == "__main__":
    main()
