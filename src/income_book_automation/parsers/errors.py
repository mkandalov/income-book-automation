class BankStatementParseError(Exception):
    """Base error for all bank-statement parsing failures."""


class BankStatementReadError(BankStatementParseError):
    """Raised when a bank-statement file cannot be read."""


class BankStatementFormatError(BankStatementParseError):
    """Raised when a bank statement has an invalid file structure."""


class MissingBankColumnError(BankStatementFormatError):
    """Raised when a required CSV column is missing."""


class DuplicateBankColumnError(BankStatementFormatError):
    """Raised when a CSV header contains duplicate columns."""


class InvalidBankRowStructureError(BankStatementFormatError):
    """Raised when a CSV row has an unexpected number of columns."""


class EmptyBankStatementError(BankStatementFormatError):
    """Raised when a statement contains no transaction rows."""


class InvalidBankRowError(BankStatementParseError):
    """Raised when a bank transaction row contains an invalid value."""
