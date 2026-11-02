from __future__ import annotations

import json
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlsplit

from astrbot.core.platform.astr_message_event import current_message_event
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.provider.provider import EmbeddingProvider
from astrbot.core.star.context import Context
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.core.utils.io import download_file
from astrbot.core.utils.media_utils import file_uri_to_path

from ..core.describer import describe
from ..util.plugin_path import get_msg_dir_in_temp


class Record:
    """Metadata for a single message."""

    def __init__(
        self,
        group_id: str,
        sender_id: str,
        msg_id: str,
        timestamp: float,
    ) -> None:
        """Store the metadata of a message.

        Args:
            group_id: The ID of the group the message is from.
            sender_id: The ID of the sender of the message.
            msg_id: The unique ID of the message.
            timestamp: The timestamp of when the message was received.
        """
        self.group_id = group_id
        self.sender_id = sender_id
        self.msg_id = msg_id
        self.timestamp = timestamp


class Msg(dict[str, Any]):
    """A simplified message tree with associated record metadata."""

    def __init__(self, simplified_msg: dict[str, Any], record: Record) -> None:
        """Store message content and its record.

        Args:
            simplified_msg: The simplified message tree.
            record: The message's group, sender, message ID and timestamp.
        """
        super().__init__(simplified_msg)
        self.record: Record = record

    @classmethod
    async def from_raw(cls, raw_msg: list[dict[str, Any]], record: Record) -> Msg:
        """Create a simplified message from raw OneBot segments.

        Args:
            raw_msg: The parsed list of message segment dictionaries.
            record: The metadata to associate with the message.

        Returns:
            The simplified message tree with its record.
        """
        return cls(await cls._simplify(raw_msg), record)

    @staticmethod
    async def _simplify(raw_msg: list[dict[str, Any]]) -> dict:
        """Expand top-level forwards once, then remove unsupported leaves.

        Resolve only forward IDs directly in the input message list through the
        current AIOCQHTTP event's bot. Replace their data with get_forward_msg
        response data, leaving nested forward references unexpanded.

        Args:
            raw_msg: The parsed list of message segment dictionaries.

        Returns:
            A new message tree whose leaf segments are text, image, file or forward.
            Structural nodes and retained content keep their order and fields.
        """
        message = deepcopy(raw_msg)

        # if forward exists, replace data with the message inside
        for segment in message:
            if segment.get("type") == "forward":
                event = cast(AiocqhttpMessageEvent, current_message_event.get())
                segment["data"] = await event.bot.call_action(
                    "get_forward_msg", id=segment["data"]["id"]
                )

        useful_type = ["text", "file", "image", "forward"]
        msg_template = {"type": "message", "data": []}
        forward_template = {"type": "forward", "data": []}

        # if real messsage
        if message[0]["type"] != "forward":
            simplified_message = deepcopy(msg_template)
            for segment in message:
                if segment["type"] not in useful_type:
                    continue
                simplified_message["data"].append(segment)
            return simplified_message

        # if forward
        def dfs(usm_node: Any, sm_node: Any, depth=1):
            nxt_usm_nodes: list
            if depth == 1:
                nxt_usm_nodes = usm_node["data"]["messages"]
            else:
                nxt_usm_nodes = usm_node["message"][0]["data"]["content"]

            for nxt_usm_node in nxt_usm_nodes:
                inner = nxt_usm_node["message"]
                if len(inner) == 1 and inner[0]["type"] == "forward":
                    forward = deepcopy(forward_template)
                    sm_node["data"].append(forward)
                    dfs(nxt_usm_node, forward, depth + 1)
                else:
                    msg = deepcopy(msg_template)
                    msg["data"] = [
                        segment for segment in inner if segment["type"] in useful_type
                    ]
                    sm_node["data"].append(msg)

        simplified_message = deepcopy(forward_template)
        dfs(message[0], simplified_message)

        return simplified_message


class MsgDirectory:
    """Store and manage files belonging to a single message directory."""

    def __init__(self, directory: str | Path) -> None:
        """Store the absolute directory path without creating it.

        Args:
            directory: Path to the message directory, which need not exist.
        """
        self.directory = Path(directory).resolve()

    def get_localized_msg_file(self) -> Path:
        """Return the localized message file path.

        Returns:
            Path to message_localized.json inside the message directory.
        """
        return self.directory / "message_localized.json"

    def get_simplified_msg_file(self) -> Path:
        """Return the message file path before attachment localization.

        Returns:
            Path to message_simplified.json with the original attachment links.
        """
        return self.directory / "message_simplified.json"

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

    def get_record(self) -> Record:
        """Read the message record from disk on each call.

        Returns:
            A new Record loaded from record.json without caching.
        """
        return Record(**json.loads(self.get_record_file().read_text(encoding="utf-8")))

    @classmethod
    async def save_msg_temporarily(cls, simplified_msg: Msg) -> MsgDirectory:
        """Save an incoming message in a temporary directory.

        Args:
            simplified_msg: Message and record to save before updating links in place.

        Returns:
            The temporary message directory at temp/msg_<msg_id>.
        """
        directory = get_msg_dir_in_temp(simplified_msg.record.msg_id)
        return await cls._save_msg(simplified_msg, directory)

    @classmethod
    async def _save_msg(cls, simplified_msg: Msg, directory: Path) -> MsgDirectory:
        """Save the simplified tree, then localize its non-text attachment links.

        Write message_simplified.json before archiving attachments. Write the
        resulting tree to message_localized.json without overwriting the snapshot.

        Args:
            simplified_msg: Message and record to save before updating links in place.
            directory: The path to the message's directory.

        Returns:
            The saved message directory.
        """
        directory.mkdir(parents=True, exist_ok=True)
        msg_dir = cls(directory)
        record_file = msg_dir.get_record_file()
        record_file.write_text(
            json.dumps(vars(simplified_msg.record), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        message = simplified_msg
        msg_dir.get_simplified_msg_file().write_text(
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
        msg_dir.get_localized_msg_file().write_text(
            json.dumps(message, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return msg_dir

    def remove_msg(self) -> None:
        """Remove this message directory and its contents."""
        shutil.rmtree(self.directory)

    def move_msg(self, new_directory: Path) -> MsgDirectory:
        """Move this directory and update localized message and description paths.

        Update remaining attachment links in description.json when present.
        Leave message_simplified.json and text components unchanged. Other
        strings only have references to this message directory updated.

        Args:
            new_directory: The destination path for the message directory.

        Returns:
            A message directory object pointing to the destination.
        """
        new_directory = new_directory.resolve()
        files = [self.get_localized_msg_file()]
        description_file = self.get_description_file()
        if description_file.exists():
            files.append(description_file)
        documents = {
            path.name: json.loads(path.read_text(encoding="utf-8")) for path in files
        }
        source_prefix = str(self.directory)
        target_prefix = str(new_directory)
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
        new_directory.parent.mkdir(parents=True, exist_ok=True)
        self.directory.rename(new_directory)
        moved = MsgDirectory(new_directory)
        for name, document in documents.items():
            (moved.directory / name).write_text(
                json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return moved

    async def generate_description(
        self,
        context: Context,
        chat_provider_id: str,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        """Generate and save the description, then return its embedding vector.

        Args:
            context: AstrBot plugin context.
            chat_provider_id: The configured chat provider used to describe resources.
            embedding_provider: The configured provider used to embed the description.

        Returns:
            The embedding vector for the complete description.json text.
        """
        description = await describe(context, chat_provider_id, self)
        text = json.dumps(description, ensure_ascii=False, indent=2)
        self.get_description_file().write_text(text, encoding="utf-8")
