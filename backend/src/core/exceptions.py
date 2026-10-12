from fastapi import HTTPException


class APIException(HTTPException):
    """Base application exception."""

    status_code = 500
    detail = "internal_server_error"

    def __init__(self, detail: str | None = None):
        super().__init__(self.status_code, detail or self.detail)


class TokenExpired(APIException):
    """Access token expired — the frontend reacts to this exact detail by refreshing."""

    status_code = 401
    detail = "token_expired"


class TokenInvalid(APIException):
    status_code = 401
    detail = "token_invalid"


class TokenMalformed(APIException):
    status_code = 401
    detail = "token_malformed"


class TokenInvalidSignature(APIException):
    status_code = 401
    detail = "token_invalid_signature"


class Unauthorized(APIException):
    status_code = 401
    detail = "unauthorized"


class Forbidden(APIException):
    status_code = 403
    detail = "forbidden"


class BadRequest(APIException):
    status_code = 400
    detail = "bad_request"


class NotFound(APIException):
    status_code = 404
    detail = "not_found"


class Conflict(APIException):
    status_code = 409
    detail = "conflict"
