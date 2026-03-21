"""
SME Auth Service - Cryptography Module

Handles encryption/decryption of sensitive data like API keys.
Uses Fernet (AES-128-CBC + HMAC) with per-user derived keys.
"""
import base64
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


class CryptoManager:
    """Manages encryption/decryption with per-user derived keys."""

    def __init__(self, master_key: Optional[str] = None):
        """
        Initialize with master encryption key.

        Args:
            master_key: Base64-encoded 32-byte key. If None, reads from MASTER_ENCRYPTION_KEY env var.
        """
        if master_key is None:
            master_key = os.environ.get("MASTER_ENCRYPTION_KEY")

        if not master_key:
            raise ValueError(
                "MASTER_ENCRYPTION_KEY environment variable is required. "
                "Generate with: openssl rand -base64 32"
            )

        try:
            self._master_key = base64.b64decode(master_key)
            if len(self._master_key) != 32:
                raise ValueError("Master key must be 32 bytes when decoded")
        except Exception as e:
            raise ValueError(f"Invalid master key format: {e}")

    def derive_user_key(self, user_id: str) -> bytes:
        """
        Derive a per-user encryption key from the master key.

        Uses PBKDF2 with user_id as salt to create unique keys per user.
        This ensures that even if one user's data is compromised,
        other users' data remains secure.

        Args:
            user_id: User's unique identifier (UUID)

        Returns:
            Fernet-compatible key (URL-safe base64 encoded)
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=user_id.encode("utf-8"),
            iterations=100_000,
        )
        derived_key = kdf.derive(self._master_key)
        return base64.urlsafe_b64encode(derived_key)

    def encrypt(self, user_id: str, plaintext: str) -> bytes:
        """
        Encrypt plaintext using user-specific key.

        Args:
            user_id: User's unique identifier
            plaintext: Text to encrypt

        Returns:
            Encrypted bytes
        """
        user_key = self.derive_user_key(user_id)
        fernet = Fernet(user_key)
        return fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, user_id: str, ciphertext: bytes) -> str:
        """
        Decrypt ciphertext using user-specific key.

        Args:
            user_id: User's unique identifier
            ciphertext: Encrypted bytes

        Returns:
            Decrypted plaintext

        Raises:
            InvalidToken: If decryption fails (wrong key or tampered data)
        """
        user_key = self.derive_user_key(user_id)
        fernet = Fernet(user_key)
        return fernet.decrypt(ciphertext).decode("utf-8")

    def mask_api_key(self, key: str, visible_chars: int = 4) -> str:
        """
        Mask an API key for display, showing only last N characters.

        Args:
            key: Full API key
            visible_chars: Number of characters to show at end

        Returns:
            Masked key like "****xxxx"
        """
        if len(key) <= visible_chars:
            return "*" * len(key)
        return "*" * (len(key) - visible_chars) + key[-visible_chars:]


# Global instance (initialized on first use)
_crypto_manager: Optional[CryptoManager] = None


def get_crypto_manager() -> CryptoManager:
    """Get or create the global CryptoManager instance."""
    global _crypto_manager
    if _crypto_manager is None:
        _crypto_manager = CryptoManager()
    return _crypto_manager


def encrypt_api_key(user_id: str, api_key: str) -> bytes:
    """Convenience function to encrypt an API key."""
    return get_crypto_manager().encrypt(user_id, api_key)


def decrypt_api_key(user_id: str, encrypted_key: bytes) -> str:
    """Convenience function to decrypt an API key."""
    return get_crypto_manager().decrypt(user_id, encrypted_key)


def mask_api_key(key: str) -> str:
    """Convenience function to mask an API key for display."""
    return get_crypto_manager().mask_api_key(key)
