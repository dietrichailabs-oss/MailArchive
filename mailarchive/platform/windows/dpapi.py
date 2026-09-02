from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


class DPAPIUnavailable(RuntimeError):
    pass


class DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), buf


def protect(data: bytes, entropy: bytes = b'MailArchive-v1') -> bytes:
    if os.name != 'nt':
        raise DPAPIUnavailable('Windows DPAPI is only available on Windows')
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob, in_buf = _blob(data)
    entropy_blob, entropy_buf = _blob(entropy)
    out_blob = DATA_BLOB()
    flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob), 'MailArchive token cache', ctypes.byref(entropy_blob),
        None, None, flags, ctypes.byref(out_blob)
    ):
        raise OSError(ctypes.get_last_error(), 'CryptProtectData failed')
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def unprotect(data: bytes, entropy: bytes = b'MailArchive-v1') -> bytes:
    if os.name != 'nt':
        raise DPAPIUnavailable('Windows DPAPI is only available on Windows')
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob, in_buf = _blob(data)
    entropy_blob, entropy_buf = _blob(entropy)
    out_blob = DATA_BLOB()
    flags = 0x01
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, ctypes.byref(entropy_blob), None, None, flags,
        ctypes.byref(out_blob)
    ):
        raise OSError(ctypes.get_last_error(), 'CryptUnprotectData failed')
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
