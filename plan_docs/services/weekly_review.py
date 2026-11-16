"""Review requirements for the facility's weekly sheet (body fields stay optional)."""


class WeeklyReviewIncompleteError(ValueError):
    pass


def owner_error(owner_name: str) -> str | None:
    return None if owner_name.strip() else "作成者を入力してください。"


def validate_review(document) -> None:
    if message := owner_error(document.owner_name):
        raise WeeklyReviewIncompleteError(message)
