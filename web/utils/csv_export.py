"""
Утилиты для безопасного экспорта данных в CSV.
Защита от CSV Formula / DDE Injection (OWASP).
"""
from typing import Any, Sequence, List

# Опасные префиксы формул в Excel, LibreOffice Calc, Google Sheets
DANGEROUS_CSV_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(val: Any) -> Any:
    """
    Если значение является строкой и начинается с опасного символа формулы
    (=, +, -, @, \\t, \\r), экранирует его лидирующим апострофом `'`,
    чтобы табличные процессоры интерпретировали ячейку исключительно как текст.
    """
    if val is None:
        return ""
    if isinstance(val, str):
        stripped = val.lstrip()
        if stripped and stripped.startswith(DANGEROUS_CSV_PREFIXES):
            return f"'{val}"
    return val


def sanitize_csv_row(row: Sequence[Any]) -> List[Any]:
    """Экранирует все ячейки строки для безопасной записи в CSV."""
    return [sanitize_csv_cell(item) for item in row]
