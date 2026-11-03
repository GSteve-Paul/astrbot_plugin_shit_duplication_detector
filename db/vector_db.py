import aiosqlite
import sqlite_vec

from astrbot.api.star import StarTools


async def init_shit_db(dimension: int) -> aiosqlite.Connection:
    """Open the vector database asynchronously and create its table if needed.

    Args:
        dimension: Embedding dimension used when creating the table.

    Returns:
        The open connection, which the caller owns and must close with await.
    """
    path = (
        StarTools.get_data_dir("astrbot_plugin_shit_duplication_detector")
        / "db.sqlite3"
    )
    db = await aiosqlite.connect(path)
    await db.enable_load_extension(True)
    await db.load_extension(sqlite_vec.loadable_path())
    await db.enable_load_extension(False)
    async with db.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS shit_vectors USING vec0(
            shit_id TEXT PRIMARY KEY,
            group_id TEXT,
            vector FLOAT[{dimension}] distance_metric=cosine
        )
        """
    ):
        await db.commit()
    return db


async def insert_shit(
    db: aiosqlite.Connection,
    group_id: str,
    shit_id: str,
    shit_vector: list[float],
) -> None:
    """Insert and commit a vector asynchronously without replacing records.

    Args:
        db: The initialized vector database connection.
        group_id: The group containing the content item.
        shit_id: The globally unique content item UUID.
        vector: The embedding generated with the database's model and dimension.
    """
    async with db.execute(
        "INSERT INTO shit_vectors (shit_id, group_id, vector) VALUES (?, ?, ?)",
        (shit_id, group_id, sqlite_vec.serialize_float32(shit_vector)),
    ):
        await db.commit()


async def update_shit(
    db: aiosqlite.Connection,
    shit_id: str,
    shit_vector: list[float],
) -> None:
    """Update and commit the vector for an existing content item.

    No rows are changed when the given ID does not exist.

    Args:
        db: The initialized vector database connection.
        shit_id: The globally unique content item UUID to update.
        vector: The replacement embedding using the database's model and dimension.
    """
    async with db.execute(
        "UPDATE shit_vectors SET vector = ? WHERE shit_id = ?",
        (sqlite_vec.serialize_float32(shit_vector), shit_id),
    ):
        await db.commit()


async def delete_shit(
    db: aiosqlite.Connection,
    shit_id: str,
) -> None:
    """Delete and commit the vector for a content item.

    No rows are changed when the given ID does not exist.

    Args:
        db: The initialized vector database connection.
        shit_id: The globally unique content item UUID to delete.
    """
    async with db.execute(
        "DELETE FROM shit_vectors WHERE shit_id = ?",
        (shit_id,),
    ):
        await db.commit()


async def search_similar_shits(
    db: aiosqlite.Connection,
    group_id: str,
    shit_vector: list[float],
    excluded_shit_id: str,
    limit: int = 5,
) -> list[tuple[str, str, float]]:
    """Find the nearest content item vectors within one group asynchronously.

    Args:
        db: The initialized vector database connection.
        group_id: The group to search within.
        vector: The query embedding using the database's model and dimension.
        limit: The maximum number of candidates to return.

    Returns:
        (group_id, shit_id, distance) tuples in ascending cosine distance order,
        or an empty list when the group has no records.
    """
    async with db.execute(
        """
        SELECT group_id, shit_id, distance
        FROM shit_vectors
        WHERE vector MATCH ?
          AND group_id = ?
          AND shit_id != ?
          AND k = ?
        ORDER BY distance ASC
        """,
        (sqlite_vec.serialize_float32(shit_vector), group_id, excluded_shit_id, limit),
    ) as cursor:
        return [
            (group_id, shit_id, distance)
            for group_id, shit_id, distance in await cursor.fetchall()
        ]
