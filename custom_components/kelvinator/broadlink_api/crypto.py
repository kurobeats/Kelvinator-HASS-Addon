"""
Broadlink DNA SDK Cryptography Module
======================================
Provides AES-128-CBC encryption/decryption compatible with Broadlink devices.

Matches the python-broadlink library's implementation:
- AES-128-CBC with a hardcoded IV (562e17996d093d28ddb3ba695a2e6f58)
- Zero-padding (NOT PKCS7)
- No checksum inside the ciphertext (checksum is in the protocol header)
"""

from hashlib import md5
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend


class AESCipher:
    """AES-128-CBC cipher compatible with Broadlink devices.

    Uses zero-padding (NUL bytes) to align to 16-byte AES block boundary.
    This is what the real python-broadlink library does.
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

    This is a convenience wrapper used by the BroadlinkDevice class.
    It zero-pads, then encrypts.

    NOTE: The checksum is NOT embedded in the ciphertext with this scheme.
    The checksum lives in the protocol header at offset 0x34.
    """
    # Zero-pad to 16-byte boundary (matching python-broadlink send_packet)
    padding_len = (16 - (len(payload) % 16)) % 16
    padded = payload + bytes(padding_len)
    return AESCipher(key, iv).encrypt(padded)


def broadlink_decrypt(encrypted: bytes, key: bytes, iv: bytes = None) -> bytes:
    """
    Decrypt a Broadlink device payload.

    Decrypts and strips trailing zero-padding.
    """
    plain = AESCipher(key, iv).decrypt(encrypted)
    # Strip zero-padding (the device uses NUL bytes, not PKCS7)
    return plain.rstrip(b'\x00')


def derive_device_key(device_id: int, key: bytes) -> bytes:
    """
    Derive a 16-byte key from the device ID and initial key.

    Broadlink uses MD5(key + device_id_as_little_endian) during auth.
    """
    id_bytes = struct.pack("<I", device_id)
    return md5(key + id_bytes).digest()
