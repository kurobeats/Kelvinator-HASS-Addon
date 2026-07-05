"""
Broadlink DNA SDK Cryptography Module
======================================
Provides AES-128-CBC encryption/decryption compatible with Broadlink devices.

Matches the python-broadlink library's implementation:
- AES-128-CBC with a hardcoded IV (562e17996d093d28ddb3ba695a2e6f58)
- PKCS7 padding (pad-byte value = number of pad bytes)
  Confirmed via Ghidra analysis of libNetworkAPI.so: bl_sdk_tfb_encode
  uses PKCS7 padding.
- No checksum inside the ciphertext (checksum is in the protocol header)
"""

import struct

from hashlib import md5
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend


class AESCipher:
    """AES-128-CBC cipher compatible with Broadlink devices.

    Uses PKCS7 padding: each pad byte equals the number of pad bytes added.
    Confirmed by Ghidra disassembly of libNetworkAPI.so bl_sdk_tfb_encode:
      pad_byte_value = 0x10 - (data_len & 0xf)
      if pad_byte_value == 0: pad_byte_value = 0x10
    """

    def __init__(self, key: bytes, iv: bytes = None):
        """
        Initialize the cipher.

        Args:
            key: 16-byte AES key
            iv: 16-byte initialization vector
        """
        if len(key) != 16:
            raise ValueError(f"Key must be 16 bytes, got {len(key)}")
        self.key = key
        self.iv = iv if iv is not None else key

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt data using AES-128-CBC.

        The caller is responsible for padding the plaintext to a multiple
        of 16 bytes before calling this method.  python-broadlink uses
        zero-padding, which is applied at the protocol layer.
        """
        if len(plaintext) % 16 != 0:
            raise ValueError(
                f"Plaintext must be 16-byte aligned, got {len(plaintext)}"
            )
        cipher = Cipher(
            algorithms.AES(self.key),
            modes.CBC(self.iv),
            backend=default_backend(),
        )
        encryptor = cipher.encryptor()
        return encryptor.update(plaintext) + encryptor.finalize()

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt data using AES-128-CBC.

        Returns raw decrypted bytes (including any padding).
        The caller should strip trailing NUL bytes if zero-padded.
        """
        cipher = Cipher(
            algorithms.AES(self.key),
            modes.CBC(self.iv),
            backend=default_backend(),
        )
        decryptor = cipher.decryptor()
        return decryptor.update(ciphertext) + decryptor.finalize()


def broadlink_encrypt(payload: bytes, key: bytes, iv: bytes = None) -> bytes:
    """
    Encrypt a payload using the Broadlink device encryption scheme.

    PKCS7-pads to 16-byte boundary, then AES-128-CBC encrypts.
    """
    # PKCS7 padding: pad byte value = number of pad bytes needed
    pad_len = 16 - (len(payload) % 16)
    if pad_len == 0:
        pad_len = 16
    padded = payload + bytes([pad_len] * pad_len)
    return AESCipher(key, iv).encrypt(padded)


def broadlink_decrypt(encrypted: bytes, key: bytes, iv: bytes = None) -> bytes:
    """
    Decrypt a Broadlink device payload.

    Decrypts and strips PKCS7 padding.
    """
    plain = AESCipher(key, iv).decrypt(encrypted)
    # Strip PKCS7 padding: last byte = pad count
    if not plain:
        return plain
    pad_len = plain[-1]
    if pad_len < 1 or pad_len > 16:
        raise ValueError(f"Invalid PKCS7 padding byte: {pad_len}")
    # Verify all pad bytes match
    if plain[-pad_len:] != bytes([pad_len] * pad_len):
        raise ValueError("Invalid PKCS7 padding")
    return plain[:-pad_len]


def derive_device_key(device_id: int, key: bytes) -> bytes:
    """
    Derive a 16-byte key from the device ID and initial key.

    Broadlink uses MD5(key + device_id_as_little_endian) during auth.
    """
    id_bytes = struct.pack("<I", device_id)
    return md5(key + id_bytes).digest()
