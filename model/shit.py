from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiosqlite

from astrbot.core.provider.provider import EmbeddingProvider

from ..db import vector_db
from ..util.plugin_path import get_partial_shit_dir, get_shits_dir
from .msg import MsgDirectory


class ShitDirectory:
    """Create and provide paths for an item containing message directories.

    Each item contains metadata.json, description.json and child directories named
    msg_<msg_id>. The metadata stores shit_id, group_id, user_id, timestamp,
    msg_ids and link_to.
    description.json stores a list of strings, each holding the complete
    description.json text of one contained message, in the same order as msg_ids.
    The group and sender are shared by all contained messages.

    Partial items live in partial_shits and have symbolic links in shits.
    Creation adds the symbolic link. release_shit replaces it with a directory
    containing the moved messages and updates paths in the description list.
    To discard a partial item, call delete_vector before remove_shit, which
    deletes its symbolic link and directory contents.

    Attributes:
        directory: Absolute directory path with symbolic links left unresolved.
    """

    def __init__(self, directory: str | Path) -> None:
        """Store the directory path without creating it or resolving symlinks.

        Args:
            directory: Path to the item or its symbolic link, which need not exist.
        """
        self.directory = Path(directory).absolute()

    def get_metadata_file(self) -> Path:
        """Return the item's metadata file path.

        Returns:
            Path to metadata.json containing shit_id, group_id, user_id, timestamp,
            msg_ids and link_to.
        """
        return self.directory / "metadata.json"

    def get_metadata(self) -> dict[str, Any]:
        """Read the item's metadata from disk on each call.

        Returns:
            A new dictionary loaded from metadata.json without caching.
        """
        return json.loads(self.get_metadata_file().read_text(encoding="utf-8"))

    def get_description_file(self) -> Path:
        """Return the file containing the ordered message descriptions.

        Returns:
            Path to description.json storing a list of message description strings.
        """
        return self.directory / "description.json"

    def get_msg_dir(self, msg_id: str) -> Path:
        """Return the path for one contained message directory.

        Args:
            msg_id: The message identifier from its Record.

        Returns:
            Path to msg_<msg_id> inside this content item's directory.
        """
        return self.directory / f"msg_{msg_id}"

    @classmethod
    def save_shit_temporarily(cls, msg_dir: MsgDirectory) -> ShitDirectory:
        """Create and return a partial item with a symbolic link from shits.

        Read the group and sender from the message's record.json. Create the item
        under partial_shits/group_<group_id>/user_<sender_id>/shit_<shit_id> and its
        symbolic link at shits/group_<group_id>/shit_<shit_id>. Both paths are
        relative to the plugin data directory. Delegate message movement,
        metadata and description writing, and link creation to _create_shit.

        Args:
            msg_dir: The saved message directory containing record.json and
                description.json to move into the new partial item.

        Returns:
            A ShitDirectory pointing to the new item in partial_shits, containing
            the moved message directory, metadata.json and description.json.
        """
        record = msg_dir.get_record()
        temp_shit_dir = get_partial_shit_dir(record.group_id, record.sender_id)
        link_dir = get_shits_dir() / f"group_{record.group_id}"
        return cls._create_shit(msg_dir, temp_shit_dir, link_dir)

    @classmethod
    def _create_shit(
        cls, msg_dir: MsgDirectory, directory: Path, link_dir: Path
    ) -> ShitDirectory:
        """Create an item with its first message, descriptions and symbolic link.

        Generate a UUID and move the message into
        directory/shit_<shit_id>/msg_<msg_id>, updating its localized paths.
        Write metadata.json using the generated shit_id, the message record's
        group, sender and timestamp, msg_ids=[record.msg_id] and the link path.
        Write description.json as a list containing the moved message's complete
        description.json text as one string.
        Finally, create link_dir/shit_<shit_id> pointing to the new item directory.

        Args:
            msg_dir: The saved message directory containing record.json and
                description.json to move into the new item.
            directory: Parent directory for the generated shit_<shit_id> directory.
            link_dir: Parent directory for the generated shit_<shit_id> symbolic
                link. Its parents are created if needed.

        Returns:
            A ShitDirectory pointing to the actual item directory, not its link.
        """
        shit_id = str(uuid4())
        record = msg_dir.get_record()
        shit_dir = cls(directory / f"shit_{shit_id}")
        msg_dir = msg_dir.move_msg(shit_dir.get_msg_dir(record.msg_id))
        link_to = link_dir / f"shit_{shit_id}"
        metadata = {
            "shit_id": shit_id,
            "group_id": record.group_id,
            "user_id": record.sender_id,
            "timestamp": record.timestamp,
            "msg_ids": [record.msg_id],
            "link_to": str(link_to),
        }
        shit_dir.get_metadata_file().write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        descriptions = [msg_dir.get_description_file().read_text(encoding="utf-8")]
        shit_dir.get_description_file().write_text(
            json.dumps(descriptions, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        link_to.parent.mkdir(parents=True, exist_ok=True)
        link_to.symlink_to(shit_dir.directory, target_is_directory=True)
        return shit_dir

    def append_msg(self, msg_dir: MsgDirectory) -> None:
        """Move a message and append its ID and description in matching order.

        Args:
            msg_dir: The saved message directory to move into this item.
        """
        metadata_file = self.get_metadata_file()
        metadata = self.get_metadata()
        description_file = self.get_description_file()
        descriptions = json.loads(description_file.read_text(encoding="utf-8"))
        record = msg_dir.get_record()
        msg_dir = msg_dir.move_msg(self.get_msg_dir(record.msg_id))
        metadata["msg_ids"].append(record.msg_id)
        descriptions.append(msg_dir.get_description_file().read_text(encoding="utf-8"))
        metadata_file.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        description_file.write_text(
            json.dumps(descriptions, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def pop_msg(self) -> None:
        """Delete the last message and remove its ID and description.

        Use the last entry in metadata.msg_ids, matching append_msg order.
        Keep the item directory and its symbolic link even when it becomes
        empty. Call update_vector separately to refresh the stored embedding.

        Raises:
            IndexError: The message ID or description list is empty.
        """
        metadata_file = self.get_metadata_file()
        metadata = self.get_metadata()
        description_file = self.get_description_file()
        descriptions = json.loads(description_file.read_text(encoding="utf-8"))
        msg_id = metadata["msg_ids"].pop()
        descriptions.pop()
        MsgDirectory(self.get_msg_dir(msg_id)).remove_msg()
        metadata_file.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        description_file.write_text(
            json.dumps(descriptions, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def release_shit(self) -> ShitDirectory:
        """Replace the symbolic link with a directory and move messages into it.

        Use MsgDirectory.move_msg to move messages in msg_ids order to link_to
        and update their localized JSON and description paths. Update description
        strings in the item's description.json, then remove the old directory
        and its remaining contents. Preserve text nodes, simplified snapshots,
        records and metadata.

        Returns:
            A new ShitDirectory at the destination. This object's directory stays
            unchanged.

        Raises:
            AssertionError: This object's directory is a symbolic link.
        """
        assert not self.directory.is_symlink()
        metadata = self.get_metadata()
        description_texts = json.loads(
            self.get_description_file().read_text(encoding="utf-8")
        )
        link_to = Path(metadata["link_to"]).absolute()
        source_prefix = str(self.directory)
        target_prefix = str(link_to)
        link_to.unlink()
        link_to.mkdir()
        released = ShitDirectory(link_to)

        for msg_id in metadata["msg_ids"]:
            MsgDirectory(self.get_msg_dir(msg_id)).move_msg(
                released.get_msg_dir(msg_id)
            )
        descriptions = [json.loads(text) for text in description_texts]
        path_pattern = re.compile(
            r"(?:"
            + re.escape(source_prefix)
            + r"(?=[/\\])|[A-Za-z][A-Za-z0-9+.-]*:|[/\\])"
            + r"""[^\s<>"'`，。；！？、（）【】]+"""
        )
        pending = list(descriptions)
        while pending:
            container = pending.pop()
            if isinstance(container, dict):
                if container.get("type") == "text":
                    continue
                entries = container.items()
            else:
                entries = enumerate(container)
            for key, value in entries:
                if isinstance(value, (dict, list)):
                    pending.append(value)
                elif isinstance(value, str):
                    container[key] = path_pattern.sub(
                        lambda match: (
                            target_prefix + match.group()[len(source_prefix) :]
                            if match.group().startswith(source_prefix)
                            and Path(match.group()).is_relative_to(self.directory)
                            else match.group()
                        ),
                        value,
                    )

        description_texts = [
            json.dumps(description, ensure_ascii=False, indent=2)
            for description in descriptions
        ]
        released.get_metadata_file().write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        released.get_description_file().write_text(
            json.dumps(description_texts, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        shutil.rmtree(self.directory)
        return released

    async def remove_shit(self) -> None:
        """Remove a partial item's symbolic link and its entire directory.

        Call on the actual partial directory, not its link or a released item.
        Read link_to from metadata.json and unlink it before removing the
        directory, including all messages and attachments. Delete the vector
        separately with delete_vector before calling this method, while the
        metadata file still exists.

        Raises:
            AssertionError: This object's directory is a symbolic link.
            OSError: Reading metadata, unlinking or removing the directory fails.
        """
        assert not self.directory.is_symlink()

        link_to = Path(self.get_metadata()["link_to"]).absolute()
        link_to.unlink()
        shutil.rmtree(self.directory)

    async def insert_vector(
        self,
        db: aiosqlite.Connection,
        embedding_provider: EmbeddingProvider,
    ) -> list[float]:
        """Embed this item's descriptions and insert the vector into the database.

        Serialize the ordered list from description.json as the embedding
        input. Read group_id and shit_id from metadata.json for the database
        record.

        Args:
            db: The initialized vector database connection.
            embedding_provider: The provider matching the database's model and dimension.
        """
        metadata = self.get_metadata()
        descriptions = json.loads(
            self.get_description_file().read_text(encoding="utf-8")
        )
        shit_id = metadata["shit_id"]
        group_id = metadata["group_id"]
        text = json.dumps(descriptions, ensure_ascii=False)
        vector = await embedding_provider.get_embedding(text)
        await vector_db.insert_shit(db, group_id, shit_id, vector)
        return vector

    async def update_vector(
        self,
        db: aiosqlite.Connection,
        embedding_provider: EmbeddingProvider,
    ) -> list[float]:
        """Re-embed this item's descriptions and update its vector in the database.

        Serialize description.json exactly as insert_vector does and update the
        record identified by shit_id in metadata.json. An absent record is not
        inserted.

        Args:
            db: The initialized vector database connection.
            embedding_provider: The provider matching the database's model and dimension.
        """
        metadata = self.get_metadata()
        descriptions = json.loads(
            self.get_description_file().read_text(encoding="utf-8")
        )
        shit_id = metadata["shit_id"]
        text = json.dumps(descriptions, ensure_ascii=False)
        vector = await embedding_provider.get_embedding(text)
        await vector_db.update_shit(db, shit_id, vector)
        return vector

    async def delete_vector(
        self,
        db: aiosqlite.Connection,
    ) -> None:
        """Delete and commit this item's vector using its saved metadata.

        Keep the directory and symbolic link intact. Call before remove_shit
        because the item ID is read from metadata.json. A missing database
        record is ignored.

        Args:
            db: The initialized vector database connection.
        """
        shit_id = self.get_metadata()["shit_id"]
        await vector_db.delete_shit(db, shit_id)
