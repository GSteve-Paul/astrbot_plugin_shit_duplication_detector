class Record:
    """Metadata for a single message."""

    def __init__(
        self,
        group_id: str,
        sender_id: str,
        msg_id: str,
        timestamp: float,
    ) -> None:
        """Store the metadata.

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
