"""Loi co kieu cua API client — tool (U4) bien chung thanh ket qua co cau truc.

Khong de `httpx` exception lot ra ngoai client: caller chi can biet 4 truong hop.
"""


class ApiError(Exception):
    """Goc cua moi loi tu API client."""

    retryable: bool = False


class InvalidArgument(ApiError):
    """Tham so sai dinh dang (slug, ma, tu khoa) — chan TRUOC khi gui request."""


class NotFound(ApiError):
    """BE tra 404: cap (truong, nganh) hoac nut phan loai khong ton tai."""


class Unavailable(ApiError):
    """BE khong tra loi duoc (timeout, mang, 403/5xx sau khi thu lai). Thu lai sau."""

    retryable = True

    def __init__(self, message: str, *, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


class BadResponse(ApiError):
    """BE tra ve thu ta khong hieu (4xx khac 404, hoac JSON sai schema) — loi cua ta."""
