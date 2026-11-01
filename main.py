import json
import time
from uuid import uuid4

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain
from astrbot.api.star import Context, Star

from .core import (
    classify,
    simplify,
    describe,
    find_duplicate,
    generate_description_vector,
    generate_roast_reply,
)
from .db import init_vector_db, insert_vector
from .model import MsgDirectory, Record


class ShitDuplicationDetectorPlugin(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)

    async def initialize(self) -> None:
        await super().initialize()

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def on_group_message(self, event: AstrMessageEvent) -> None:
        """Handle group messages without requiring a bot mention.

        Args:
            event: Incoming AstrBot message event.
        """
        # Get AI providers
        umo = event.unified_msg_origin
        chat_provider_id = await self.context.get_current_chat_provider_id(umo=umo)
        embedding_provider = self.context.get_all_embedding_providers()[0]
        self.db = await init_vector_db(embedding_provider.get_dim())
        rerank_provider = self.context.provider_manager.rerank_provider_insts[0]

        # Get the message content and save it temporarily
        raw_msg = event.get_messages()
        msg = await simplify([await part.to_dict() for part in raw_msg])

        if len(msg) == 0:
            logger.info("Message is empty, ignoring.")
            return
        
        this_record = Record(
            group_id=event.get_group_id(),
            sender_id=event.get_sender_id(),
            msg_id=str(uuid4()),
            timestamp=time.time(),
        )
        temp_this_dir = await MsgDirectory.save_msg_temporarily(msg, this_record)
        is_shit = await classify(self.context, chat_provider_id, temp_this_dir)
        if not is_shit:
            logger.info("Message is not shit, removing temporary directory.")
            temp_this_dir.remove_msg()
            return

        # If the message is shit, describe it, generate its description vector, and check for duplicates
        logger.info("Message is shit, checking for duplicates.")

        await describe(self.context, chat_provider_id, temp_this_dir)
        description_vector = await generate_description_vector(
            embedding_provider, temp_this_dir
        )

        is_duplicate = await find_duplicate(
            self.context,
            chat_provider_id,
            self.db,
            rerank_provider,
            this_record.group_id,
            temp_this_dir,
            description_vector,
        )
        if is_duplicate is None:
            logger.info("No duplicates found, saving message permanently.")
            temp_this_dir.temp_to_permanent()
            await insert_vector(
                self.db,
                this_record.group_id,
                this_record.msg_id,
                description_vector,
            )
        else:
            logger.info("Duplicate found, generating roast reply.")
            reply = await generate_roast_reply(
                self.context, chat_provider_id, is_duplicate, temp_this_dir
            )
            temp_this_dir.remove_msg()
            await event.send(
                event.chain_result([At(qq=this_record.sender_id), Plain(reply)])
            )

    async def terminate(self) -> None:
        await self.db.close()
        await super().terminate()
