from pathlib import Path

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext


@dataclass
class MsgDirectoryTool(FunctionTool[AstrAgentContext]):
    name: str = "message_directory_reader"
    description: str = "A tool for reading a message directory and contents inside it."
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
