"""Errors the service raises, which the API turns into error envelopes and the CLI into exit code 2."""

from jevtester.schemas import ApiErrorCode, ErrorDetail


class ServiceError(Exception):
    """An operation can't be done as asked."""

    code: ApiErrorCode = "internal"

    def __init__(self, message: str, *, field: str | None = None, details: list[ErrorDetail] | None = None) -> None:
        """Describe the error.

        Args:
            message: What's wrong, for a person.
            field: The dotted path of the input field at fault, when there is one.
            details: Every error, when there are several, like a policy's validation errors.
        """
        super().__init__(message)
        self.field = field
        self.details = details


class InvalidRequestError(ServiceError):
    """The input is invalid, like an unknown target or a malformed suite file."""

    code = "invalid_request"


class NotFoundError(ServiceError):
    """No suite, question set, version, run, or case has that name."""

    code = "not_found"


class ConflictError(ServiceError):
    """The change clashes with what exists, like a case id the suite already has."""

    code = "conflict"
