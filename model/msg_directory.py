from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from astrbot.api.star import StarTools
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.core.utils.io import download_file
from astrbot.core.utils.media_utils import file_uri_to_path

from .record import Record


class MsgDirectory:
    """Store and manage files belonging to a single message directory."""

    def __init__(self, directory: str | Path) -> None:
        """Store the absolute directory path without creating it.

        Args:
            directory: Path to the message directory, which need not exist.
        """
        self.directory = Path(directory).resolve()

    def get_msg_file(self) -> Path:
        """Return the message file path.

        Returns:
            Path to message.json inside the message directory.
        """
        return self.directory / "message.json"

    def get_description_file(self) -> Path:
        """Return the message description file path.

        Returns:
            Path to description.json inside the message directory.
        """
        return self.directory / "description.json"

    def get_attachment_dir(self) -> Path:
        """Return the attachment directory path.

        Returns:
            Path to attachments inside the message directory.
        """
        return self.directory / "attachments"

    def get_record_file(self) -> Path:
        """Return the record file path.

        Returns:
            Path to record.json inside the message directory.
        """
        return self.directory / "record.json"

    @classmethod
    async def save_msg_temporarily(
        cls, simplified_msg: dict, record: Record
    ) -> MsgDirectory:
        """Save an incoming message in a temporary directory.

        Args:
            simplified_msg: Simplified message tree whose links are updated in place.
            record: The record for the message.

        Returns:
            The temporary message directory.
        """
        data_dir = StarTools.get_data_dir("astrbot_plugin_shit_duplication_detector")
        directory = data_dir / f"group-{record.group_id}" / f"msg-temp-{record.msg_id}"
        return await cls.save_msg(simplified_msg, record, directory)

    @classmethod
    async def save_msg(
        cls, simplified_msg: dict, record: Record, directory: Path
    ) -> MsgDirectory:
        """Save a simplified tree with absolute attachment paths in non-text leaves.

        Args:
            simplified_msg: Simplified message tree whose links are updated in place.
            record: The message's group, sender, message ID and timestamp.
            directory: The path to the message's directory.

        Returns:
            The saved message directory.
        """
        directory.mkdir(parents=True, exist_ok=True)
        record_file = directory / "record.json"
        record_file.write_text(
            json.dumps(vars(record), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        message = simplified_msg
        msg_file = directory / "message.json"
        msg_file.write_text(
            json.dumps(message, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        data_dir = Path(get_astrbot_data_path()).resolve()
        attachments = (directory / "attachments").resolve()
        link_pattern = re.compile(
            r"(?:https?://|file://|"
            + re.escape(str(data_dir))
            + r"[/\\]|(?:\./)?data[/\\])"
            + r"""[^\s<>"'`，。；！？、（）【】]+""",
            re.IGNORECASE,
        )
        string_fields = []
        links: dict[str, str] = {}
        pending = [message]
        while pending:
            node = pending.pop()
            if node["type"] in {"forward", "message"}:
                pending.extend(reversed(node["data"]))
                continue
            if node["type"] == "text":
                continue

            # Only leaf data contains attachments; container metadata stays intact.
            leaf_data = node["data"]
            preferred_file = leaf_data.get("file", "")
            pending_fields: list[Any] = [leaf_data]
            while pending_fields:
                container = pending_fields.pop()
                if isinstance(container, dict):
                    entries = container.items()
                else:
                    entries = enumerate(container)
                children = []
                for key, value in entries:
                    if isinstance(value, (dict, list)):
                        children.append(value)
                    elif isinstance(value, str):
                        string_fields.append((container, key, value))
                        for match in link_pattern.finditer(value):
                            links.setdefault(match.group(), preferred_file)
                pending_fields.extend(reversed(children))

        replacements = {}
        for raw_link, preferred_file in links.items():
            link = raw_link.rstrip(".,;:!?)]}")
            ending = raw_link[len(link) :]
            download_target = None
            try:
                parsed = urlsplit(link)
                name_path = urlsplit(preferred_file or link).path
                name = Path(unquote(name_path)).name
                if not name or name == ".." or name_path.endswith("/"):
                    continue
                target = attachments / name
                if not target.is_file():
                    if parsed.scheme.lower() in {"http", "https"}:
                        attachments.mkdir(exist_ok=True)
                        download_target = target
                        await download_file(
                            link, str(target), allow_insecure_ssl_fallback=False
                        )
                    else:
                        source = Path(file_uri_to_path(link))
                        if not source.is_absolute():
                            source = data_dir.parent / source
                        source = source.resolve()
                        if not source.is_relative_to(data_dir) or not source.is_file():
                            continue
                        if source.is_relative_to(attachments):
                            target = source
                        else:
                            attachments.mkdir(exist_ok=True)
                            target.hardlink_to(source)
                replacements[raw_link] = str(target) + ending
            except Exception:
                # Keep failed links and never reuse a partial download.
                if download_target is not None:
                    download_target.unlink(missing_ok=True)

        for container, key, value in string_fields:
            container[key] = link_pattern.sub(
                lambda match: replacements.get(match.group(), match.group()),
                value,
            )
        msg_file.write_text(
            json.dumps(message, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return cls(directory)

    def remove_msg(self) -> None:
        """Remove this message directory and its contents."""
        shutil.rmtree(self.directory)

    def temp_to_permanent(self) -> MsgDirectory:
        """Rename this directory and update message and description paths.

        Update remaining attachment links in description.json when present.
        Plain components remain unchanged. Other strings only have references
        to this message directory updated.

        Returns:
            The permanent message directory.
        """
        record = json.loads(self.get_record_file().read_text(encoding="utf-8"))
        files = [self.get_msg_file()]
        description_file = self.get_description_file()
        if description_file.exists():
            files.append(description_file)
        documents = {
            path.name: json.loads(path.read_text(encoding="utf-8")) for path in files
        }
        permanent_dir = self.directory.parent / f"msg-{record['msg_id']}"
        source_prefix = str(self.directory)
        target_prefix = str(permanent_dir)
        path_pattern = re.compile(
            r"(?:"
            + re.escape(source_prefix)
            + r"(?=[/\\])|[A-Za-z][A-Za-z0-9+.-]*:|[/\\])"
            + r"""[^\s<>"'`，。；！？、（）【】]+"""
        )
        pending = list(documents.values())
        while pending:
            container = pending.pop()
            if isinstance(container, dict):
                # Skip the whole Plain component, including nested ones.
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
        self.directory.rename(permanent_dir)
        permanent = MsgDirectory(permanent_dir)
        for name, document in documents.items():
            (permanent.directory / name).write_text(
                json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return permanent
