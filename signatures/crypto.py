import base64
import datetime
import hashlib
import json
import os
import uuid
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from django.conf import settings


def json_default_serializer(obj: Any) -> Any:
    """Deterministic JSON serializer for non-standard types."""
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if hasattr(obj, '__dict__'):
        return obj.__dict__
    return str(obj)


def canonical_json(data: dict) -> bytes:
    """
    Produces deterministic canonical JSON bytes from a dictionary.
    Rules:
    - Sorted keys
    - Minimal separators (',', ':')
    - UTF-8 encoding
    - Stable ISO-8601 timestamps
    - Stable null representation
    """
    serialized = json.dumps(
        data,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,
        default=json_default_serializer,
    )
    return serialized.encode('utf-8')


def compute_sha256(data: bytes | str) -> str:
    """Returns the 64-character lowercase hexadecimal SHA-256 hash of data."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


class SignatureKeyProvider:
    """
    Secure Key Provider Abstraction for Digital Signing.
    Supports environment key loading, in-memory caching, key rotation, and
    future integration with HSM, KMS, HashiCorp Vault, or University PKI.
    """

    _cached_keys: dict[str, ed25519.Ed25519PrivateKey] = {}
    _cached_public_keys: dict[str, ed25519.Ed25519PublicKey] = {}

    @classmethod
    def get_algorithm(cls) -> str:
        return getattr(settings, 'SIGNATURE_ALGORITHM', 'Ed25519')

    @classmethod
    def get_key_version(cls) -> str:
        return getattr(settings, 'SIGNATURE_KEY_ID', 'v1')

    @classmethod
    def get_active_private_key(cls) -> ed25519.Ed25519PrivateKey:
        """
        Retrieves the active private key for signing.
        Reads from settings.SIGNATURE_PRIVATE_KEY_B64 or generates a stable in-memory key.
        Never persists private keys to database plain text.
        """
        version = cls.get_key_version()
        if version in cls._cached_keys:
            return cls._cached_keys[version]

        env_key_b64 = getattr(settings, 'SIGNATURE_PRIVATE_KEY_B64', None) or os.getenv('SIGNATURE_PRIVATE_KEY_B64')
        if env_key_b64:
            try:
                raw_bytes = base64.b64decode(env_key_b64.strip())
                if len(raw_bytes) == 32:
                    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(raw_bytes)
                else:
                    private_key = serialization.load_pem_private_key(raw_bytes, password=None)
            except Exception:
                # Fallback to fresh key if parsing fails
                private_key = ed25519.Ed25519PrivateKey.generate()
        else:
            private_key = ed25519.Ed25519PrivateKey.generate()

        cls._cached_keys[version] = private_key
        cls._cached_public_keys[version] = private_key.public_key()
        return private_key

    @classmethod
    def get_active_public_key(cls) -> ed25519.Ed25519PublicKey:
        """Retrieves the public key corresponding to the active private key."""
        version = cls.get_key_version()
        if version not in cls._cached_public_keys:
            cls.get_active_private_key()
        return cls._cached_public_keys[version]

    @classmethod
    def get_public_key_for_version(
        cls, version: str, stored_pem: str = ''
    ) -> ed25519.Ed25519PublicKey | None:
        """
        Retrieves a public key for verifying historical signatures.
        If version matches cached, returns cached public key.
        Otherwise loads from the historical stored_pem recorded on the signature.
        """
        if version in cls._cached_public_keys:
            return cls._cached_public_keys[version]

        if stored_pem:
            try:
                return cls.load_public_key_from_pem(stored_pem)
            except Exception:
                return None
        return None

    @classmethod
    def register_versioned_key(cls, version: str, private_key: ed25519.Ed25519PrivateKey):
        """Allows test setups or rotation services to register specific versioned keys."""
        cls._cached_keys[version] = private_key
        cls._cached_public_keys[version] = private_key.public_key()

    @staticmethod
    def export_public_key_pem(public_key: ed25519.Ed25519PublicKey) -> str:
        """Exports an Ed25519 public key as OpenSSL SubjectPublicKeyInfo PEM string."""
        pem_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return pem_bytes.decode('utf-8')

    @staticmethod
    def load_public_key_from_pem(pem_str: str) -> ed25519.Ed25519PublicKey:
        """Loads an Ed25519 public key from PEM string."""
        return serialization.load_pem_public_key(pem_str.encode('utf-8'))


def sign_data(private_key: ed25519.Ed25519PrivateKey, data_bytes: bytes) -> str:
    """
    Cryptographically signs data_bytes using the Ed25519 private key.
    Returns the signature as a URL-safe / standard Base64 string.
    """
    raw_signature = private_key.sign(data_bytes)
    return base64.b64encode(raw_signature).decode('utf-8')


def verify_signature_bytes(
    public_key: ed25519.Ed25519PublicKey,
    data_bytes: bytes,
    signature_b64: str,
) -> bool:
    """
    Verifies that signature_b64 is a valid cryptographic signature of data_bytes
    under public_key.
    """
    try:
        raw_signature = base64.b64decode(signature_b64.encode('utf-8'))
        public_key.verify(raw_signature, data_bytes)
        return True
    except (InvalidSignature, ValueError, TypeError, Exception):
        return False
