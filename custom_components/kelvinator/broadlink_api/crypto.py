"""
Broadlink DNA SDK Cryptography Module
======================================
Provides AES-128-CBC encryption/decryption compatible with Broadlink devices.

The Broadlink protocol uses AES-128-CBC with:
- 16-byte key (device key)
- 16-byte IV (initialization vector, typically derived from device ID + key)
- PKCS7 padding
- Little-endian byte order for certain operations
"""

import struct
from hashlib import md5
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend


class AESCipher:
    """AES-128-CBC cipher compatible with Broadlink devices."""

    def __init__(self, key: bytes, iv: bytes = None):
        """
        Initialize the cipher.

        Args:
            key: 16-byte AES key
            iv: 16-byte initialization vector. If None, defaults to the key.
        """
        if len(key) != 16:
            raise ValueError(f"Key must be 16 bytes, got {len(key)}")
        self.key = key
        self.iv = iv if iv is not None else key

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt data using AES-128-CBC with PKCS7 padding."""
        padded = _pkcs7_pad(plaintext, 16)
        cipher = Cipher(
            algorithms.AES(self.key),
            modes.CBC(self.iv),
            backend=default_backend(),
        )
        encryptor = cipher.encryptor()
        return encryptor.update(padded) + encryptor.finalize()

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt data using AES-128-CBC and remove PKCS7 padding."""
        cipher = Cipher(
            algorithms.AES(self.key),
            modes.CBC(self.iv),
            backend=default_backend(),
        )
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        return _pkcs7_unpad(padded)


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    """Apply PKCS7 padding."""
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


def _pkcs7_unpad(data: bytes) -> bytes:
    """Remove PKCS7 padding."""
    if not data:
        return data
    pad_len = data[-1]
    if pad_len > 16 or pad_len == 0:
        raise ValueError("Invalid PKCS7 padding")
    if data[-pad_len:] != bytes([pad_len] * pad_len):
        raise ValueError("Invalid PKCS7 padding")
    return data[:-pad_len]


def broadlink_encrypt(payload: bytes, key: bytes, iv: bytes = None) -> bytes:
    """
    Encrypt a payload using the Broadlink device encryption scheme.

    The Broadlink scheme:
    1. Compute a checksum of the payload (sum of all bytes as u16, little-endian)
    2. Prepend the checksum to the payload
    3. Apply PKCS7 padding
    4. AES-128-CBC encrypt
    """
    checksum = sum(payload) & 0xFFFF
    full_payload = struct.pack("<H", checksum) + payload
    return AESCipher(key, iv).encrypt(full_payload)


def broadlink_decrypt(encrypted: bytes, key: bytes, iv: bytes = None) -> bytes:
    """
    Decrypt a Broadlink device payload.

    Returns the plaintext with the 2-byte checksum stripped.
    """
    plain = AESCipher(key, iv).decrypt(encrypted)
    if len(plain) < 2:
        raise ValueError("Decrypted payload too short")
    # Verify checksum
    checksum_recv = struct.unpack("<H", plain[:2])[0]
    payload = plain[2:]
    checksum_calc = sum(payload) & 0xFFFF
    if checksum_recv != checksum_calc:
        raise ValueError(
            f"Checksum mismatch: received 0x{checksum_recv:04x}, "
            f"calculated 0x{checksum_calc:04x}"
        )
    return payload


def derive_device_key(device_id: int, key: bytes) -> bytes:
    """
    Derive the full 16-byte device key from the device ID and initial key.

    Broadlink uses md5 of (key + device_id_as_little_endian) as the IV.
    """
    id_bytes = struct.pack("<I", device_id)
    return md5(key + id_bytes).digest()
