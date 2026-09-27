from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler


class BusinessRuleError(APIException):
    """A request that is well formed but breaks a business rule."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "business_rule"

    def __init__(self, message, code="business_rule", fields=None):
        self.fields = fields or {}
        super().__init__(detail=message, code=code)


class ConflictError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This record was changed by someone else. Reload it and apply your change again."
    default_code = "stale_version"


class ServiceUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "unavailable"


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    data = response.data
    code = getattr(exc, "default_code", "error")
    if hasattr(exc, "get_codes"):
        codes = exc.get_codes()
        if isinstance(codes, str):
            code = codes
    if isinstance(data, dict) and "detail" in data:
        body = {"detail": str(data["detail"]), "code": code}
        fields = getattr(exc, "fields", None)
        if fields:
            body["fields"] = fields
    elif isinstance(data, dict):
        body = {"detail": "Please correct the highlighted fields.", "code": "invalid", "fields": data}
    else:
        body = {"detail": "; ".join(str(x) for x in data), "code": code}
    response.data = body
    return response


def require_version(instance, submitted):
    """Raise ConflictError when a stale version is submitted (CRM03)."""
    if submitted is None:
        raise BusinessRuleError("The record version is required to save changes.", code="version_required")
    try:
        submitted = int(submitted)
    except (TypeError, ValueError):
        raise BusinessRuleError("The record version must be a number.", code="version_required")
    if submitted != instance.version:
        raise ConflictError()
