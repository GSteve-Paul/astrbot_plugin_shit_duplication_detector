import aiosqlite
import sqlite_vec

from astrbot.api.star import StarTools

async def init_vector_db(dimension: int) -> aiosqlite.Connection:
    """Open the vector database asynchronously and create its table if needed.

    Args:
        dimension: Embedding dimension used when creating the table.

    Returns:
        The open connection, which the caller owns and must close with await.
    """
    path = (
        StarTools.get_data_dir("astrbot_plugin_shit_duplication_detector")
        / "vectors.sqlite3"
    )
    db = await aiosqlite.connect(path)
    await db.enable_load_extension(True)
    await db.load_extension(sqlite_vec.loadable_path())
    await db.enable_load_extension(False)
    async with db.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS message_vectors USING vec0(
            msg_id TEXT PRIMARY KEY,
            group_id TEXT,
            vector FLOAT[{dimension}] distance_metric=cosine
        )
        """
    ):
        await db.commit()
    return db


async def insert_vector(
    db: aiosqlite.Connection,
    group_id: str,
    msg_id: str,
    vector: list[float],
) -> None:
    """Insert and commit a vector asynchronously without replacing records.

    Args:
        db: The initialized vector database connection.
        group_id: The group containing the message.
        msg_id: The globally unique message UUID.
        vector: The embedding generated with the database's model and dimension.
    """
    async with db.execute(
        "INSERT INTO message_vectors (msg_id, group_id, vector) VALUES (?, ?, ?)",
        (msg_id, group_id, sqlite_vec.serialize_float32(vector)),
    ):
        await db.commit()


async def search_similar_vectors(
    db: aiosqlite.Connection,
    group_id: str,
    vector: list[float],
    limit: int = 5,
) -> list[tuple[str, str, float]]:
    """Find the nearest message vectors within one group asynchronously.

    Args:
        db: The initialized vector database connection.
        group_id: The group to search within.
        vector: The query embedding using the database's model and dimension.
        limit: The maximum number of candidates to return.

    Returns:
        Message UUID and cosine distance pairs in ascending distance order,
        or an empty list when the group has no records.
    """
    async with db.execute(
        """
        SELECT group_id, msg_id, distance
        FROM message_vectors
        WHERE vector MATCH ?
          AND group_id = ?
          AND k = ?
        ORDER BY distance ASC
        """,
        (sqlite_vec.serialize_float32(vector), group_id, limit),
    ) as cursor:
        return [(group_id, msg_id, distance) for group_id, msg_id, distance in await cursor.fetchall()]
