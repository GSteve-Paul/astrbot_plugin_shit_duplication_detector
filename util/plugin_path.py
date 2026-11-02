"""Build absolute plugin paths without creating directories.

AstrBot supplies the plugin-data root, and metadata.yaml supplies the plugin
name. Paths beneath that plugin directory follow this layout:

    <plugin_name>/
        temp/msg_<msg_id>/
        partial_shits/group_<group_id>/user_<user_id>/
        shits/group_<group_id>/shit_<shit_id>/

Path helpers return pathlib.Path objects even when the directories do not yet
exist. Callers are responsible for creating directories when saving content.
"""

from pathlib import Path

import yaml

from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path


def get_name() -> str:
    """Read the plugin name from its metadata.

    Locate metadata.yaml relative to this module so lookup is independent of
    the process's current working directory.

    Returns:
        The name field declared in the plugin's metadata.yaml, as a string.
    """
    metadata_file = Path(__file__).resolve().parents[1] / "metadata.yaml"
    return yaml.safe_load(metadata_file.read_text(encoding="utf-8"))["name"]


def get_data_path() -> Path:
    """Return the plugin's data directory path.

    Use AstrBot's configured plugin-data root and the name from metadata.yaml.

    Returns:
        Absolute path to <plugin_data>/<plugin_name>.
    """
    return Path(get_astrbot_plugin_data_path()) / get_name()


def get_temp_path() -> Path:
    """Return the root path for temporary message directories.

    Returns:
        Absolute path to <plugin_data>/<plugin_name>/temp.
    """
    return get_data_path() / "temp"


def get_shits_dir() -> Path:
    """Return the permanent content directory path.

    Returns:
        Absolute path to <plugin_data>/<plugin_name>/shits.
    """
    return get_data_path() / "shits"


def get_partial_shits_dir() -> Path:
    """Return the root path for partial content grouped by group and user.

    Returns:
        Absolute path to <plugin_data>/<plugin_name>/partial_shits.
    """
    return get_data_path() / "partial_shits"


def get_partial_shit_dir(group_id: str, user_id: str) -> Path:
    """Return a user's partial content directory within a group.

    Args:
        group_id: The group containing the message.
        user_id: The user contributing the content.

    Returns:
        Absolute path to partial_shits/group_<group_id>/user_<user_id> under the
        plugin's data directory.
    """
    return get_partial_shits_dir() / f"group_{group_id}" / f"user_{user_id}"


def get_shit_dir_in_shits(group_id: str, shit_id: str) -> Path:
    """Return a permanent content record's directory within a group.

    Args:
        group_id: The group containing the record.
        shit_id: The identifier of the saved content.

    Returns:
        Absolute path to shits/group_<group_id>/shit_<shit_id> under the
        plugin's data directory.
    """
    return get_shits_dir() / f"group_{group_id}" / f"shit_{shit_id}"


def get_msg_dir_in_temp(msg_id: str) -> Path:
    """Return the temporary directory path for one message.

    Args:
        msg_id: The message identifier used in the directory name.

    Returns:
        Absolute path to temp/msg_<msg_id> under the plugin's data directory.
    """
    return get_temp_path() / f"msg_{msg_id}"
