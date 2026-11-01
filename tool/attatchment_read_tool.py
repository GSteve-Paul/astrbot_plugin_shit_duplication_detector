from pathlib import Path

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api.star import StarTools
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.computer.booters.local import LocalBooter
from astrbot.core.computer.file_read_utils import read_file_tool_result


@dataclass
class AttachmentReadTool(FunctionTool[AstrAgentContext]):
    """Read local attachments using AstrBot's native file parsers."""

    name: str = "attachment_reader"
    description: str = (
        "Read a local file by its absolute path. Supports text, images, PDF, DOCX "
        "and EPUB. Use offset and limit to read large text in sections. If a "
        "converted text path is returned, use this tool to read that file."
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path of the local file to read.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Optional starting line offset, indexed from 0.",
                    "minimum": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Optional maximum number of lines to read.",
                    "minimum": 1,
                },
            },
            "required": ["path"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs,
    ) -> ToolExecResult:
        """Read an attachment without requiring a computer runtime setting.

        Args:
            context: The agent's execution context.
            **kwargs: Tool arguments containing the absolute path and optional
                offset and limit for the read window.

        Returns:
            Native text or image tool output, including any read-limit notices.

        Raises:
            ValueError: The path is relative or the read window is invalid.
        """
        path = kwargs["path"]
        offset = kwargs.get("offset")
        limit = kwargs.get("limit")
        file_path = Path(path)
        if not file_path.is_absolute():
            raise ValueError("`path` must be an absolute path.")
        if offset is not None and offset < 0:
            raise ValueError("`offset` must be greater than or equal to 0.")
        if limit is not None and limit < 1:
            raise ValueError("`limit` must be greater than or equal to 1.")

        data_dir = StarTools.get_data_dir("astrbot_plugin_shit_duplication_detector")
        return await read_file_tool_result(
            LocalBooter(),
            local_mode=True,
            path=str(file_path.resolve()),
            offset=offset,
            limit=limit,
            workspace_dir=str(data_dir),
        )
