class BankStatementParseError(Exception):
    """Base error for all bank-statement parsing failures."""


class BankStatementReadError(BankStatementParseError):
    """Raised when a bank-statement file cannot be read."""


class BankStatementFormatError(BankStatementParseError):
    """Raised when a bank statement has an invalid file structure."""


class MissingBankColumnError(BankStatementFormatError):
    """Raised when a required CSV column is missing."""


class InvalidBankRowError(BankStatementParseError):
    """Raised when a bank transaction row contains an invalid value."""
