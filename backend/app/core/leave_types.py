"""Stable quota keys with compatibility for existing Chinese labels."""

LEAVE_TYPE_LABELS = {'annual': '年假', 'sick': '病假', 'personal': '事假', 'other': '其他假'}


def leave_type_code(value: str) -> str:
    return next((code for code, label in LEAVE_TYPE_LABELS.items() if value == label), value)


def leave_type_aliases(value: str) -> tuple[str, ...]:
    code = leave_type_code(value)
    label = LEAVE_TYPE_LABELS.get(code)
    return (code, label) if label else (code,)


def leave_type_label(value: str) -> str:
    return LEAVE_TYPE_LABELS.get(leave_type_code(value), value)
