import aiosqlite

from astrbot.api.star import StarTools


async def init_attachment_db() -> aiosqlite.Connection:
    """Open the persistent attachment description cache and create its table.

    Returns:
        The connection, which the caller must close with await.
    """
    path = (
        StarTools.get_data_dir("astrbot_plugin_shit_duplication_detector")
        / "attachment_descriptions.sqlite3"
    )
    db = await aiosqlite.connect(path)
    try:
        async with db.execute(
            """
            CREATE TABLE IF NOT EXISTS attachment_descriptions (
                hash TEXT PRIMARY KEY,
                description TEXT NOT NULL
            )
            """
        ):
            await db.commit()
    except BaseException:
        await db.close()
        raise
    return db


async def get_attachment_description(
    db: aiosqlite.Connection,
    attachment_hash: str,
) -> str | None:
    """Look up a description by the attachment's SHA-256 digest.

    Args:
        db: The open attachment cache connection.
        attachment_hash: Hexadecimal SHA-256 digest of the file's original bytes.

    Returns:
        The stored description, or None when the hash is not cached.
    """
    async with db.execute(
        "SELECT description FROM attachment_descriptions WHERE hash = ?",
        (attachment_hash,),
    ) as cursor:
        row = await cursor.fetchone()
    return row[0] if row is not None else None


async def save_attachment_description(
    db: aiosqlite.Connection,
    attachment_hash: str,
    description: str,
) -> None:
    """Store a successful description without replacing an existing entry.

    Args:
        db: The open attachment cache connection.
        attachment_hash: Hexadecimal SHA-256 digest of the file's original bytes.
        description: The nonblank description generated for this attachment.
    """
    async with db.execute(
        """
        INSERT INTO attachment_descriptions (hash, description)
        VALUES (?, ?)
        ON CONFLICT(hash) DO NOTHING
        """,
        (attachment_hash, description),
    ):
        await db.commit()
