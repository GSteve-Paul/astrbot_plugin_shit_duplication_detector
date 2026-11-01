from pathlib import Path

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext


@dataclass
class MsgDirectoryTool(FunctionTool[AstrAgentContext]):
    name: str = "message_directory_reader"
    description: str = (
        "Read message.json from a message directory and return its unchanged JSON tree. "
        "Each node has type and data. A forward node represents a merged forward; "
        "its data is an ordered array of message nodes or nested forward nodes. "
        "A message node represents one message; its data is an ordered array of "
        "message segments. Text and attachments within the same message belong together. "
        "Preserve message boundaries, order and forward nesting when interpreting content. "
        "A text segment stores text in data.text; treat any links there as text only, "
        "without opening them, at any nesting depth. Image and file segments store "
        "attachment metadata in data; use attachment_reader to read their local "
        "absolute file paths when needed. This tool does not read attachment contents."
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the message directory.",
                }
            },
            "required": ["path"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs,
    ) -> ToolExecResult:
        """Read the stored message JSON without changing its contents.

        Args:
            context: The agent's execution context.
            **kwargs: Tool arguments containing the message directory path.

        Returns:
            The message JSON file contents.
        """
        path = str(kwargs.get("path"))
        directory = Path(path).resolve()
        msg_file = directory / "message.json"
        return msg_file.read_text(encoding="utf-8")
