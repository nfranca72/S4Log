from __future__ import annotations

from app.db.connection import db_cursor


def create_or_update_user(user_id: str, name: str, active: int) -> dict[str, object]:
    with db_cursor() as (cursor, _conn):
        columns = _users_columns(cursor)
        user_id_column = _resolve_user_id_column(columns)
        profile_value = 10
        cursor.execute(
            f"""
            UPDATE [Users]
            SET [Username] = ?,
                [Password] = ?,
                [Profile] = ?,
                [Active] = ?
            WHERE [{user_id_column}] = ?
            """,
            (name, "1234", profile_value, active, user_id),
        )

        if cursor.rowcount and cursor.rowcount > 0:
            action = "updated"
        else:
            cursor.execute(
                f"""
                INSERT INTO [Users] (
                    [{user_id_column}],
                    [Username],
                    [Password],
                    [Profile],
                    [Active]
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, name, "1234", profile_value, active),
            )
            action = "created"

    return {
        "UserId": user_id,
        "name": name,
        "Active": active,
        "Action": action,
    }


def _users_columns(cursor) -> dict[str, dict[str, str]]:
    cursor.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'Users'
        """
    )
    return {
        str(row[0]).lower(): {
            "name": str(row[0]),
            "data_type": str(row[1]).lower(),
        }
        for row in cursor.fetchall()
    }


def _resolve_user_id_column(columns: dict[str, dict[str, str]]) -> str:
    for candidate in ("UserID", "UserId", "UsrID", "User", "Login", "Code"):
        column_info = columns.get(candidate.lower())
        if column_info:
            return column_info["name"]

    raise ValueError(
        "Could not find a user id column in table Users. Expected one of: "
        "UserID, UserId, UsrID, User, Login, Code."
    )
