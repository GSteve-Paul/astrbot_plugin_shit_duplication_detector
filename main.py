import time
from uuid import uuid4

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain
from astrbot.api.star import Context, Star

from .core.classifier import classify, classify_supplement
from .core.matcher import find_duplicate, find_duplicate_msg
from .core.replier import generate_msg_roast_reply, generate_roast_reply
from .db.vector_db import init_shit_db
from .model.msg import Msg, MsgDirectory, Record
from .model.shit import ShitDirectory
from .util.plugin_path import get_partial_shit_dir


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
        self.db = await init_shit_db(embedding_provider.get_dim())
        rerank_provider = self.context.provider_manager.rerank_provider_insts[0]

        # Get the message content and save it temporarily
        raw_msg = event.get_messages()
        record = Record(
            group_id=event.get_group_id(),
            sender_id=event.get_sender_id(),
            msg_id=str(uuid4()),
            timestamp=time.time(),
        )
        msg = await Msg.from_raw([await part.to_dict() for part in raw_msg], record)
        if len(msg) == 0:
            logger.info("Message is empty, ignoring.")
            return

        temp_msg_dir = await MsgDirectory.save_msg_temporarily(msg)
        await temp_msg_dir.generate_description(
            self.context, chat_provider_id, embedding_provider
        )
        partial_shit_root_dir = get_partial_shit_dir(record.group_id, record.sender_id)
        partial_shit_dir = next(
            (
                ShitDirectory(path)
                for path in partial_shit_root_dir.glob("shit_*")
                if path.is_dir()
            ),
            None,
        )

        shit_dir_need_check = None
        shit_vector = None
        if partial_shit_dir:
            same = await classify_supplement(
                self.context, chat_provider_id, partial_shit_dir, temp_msg_dir
            )
            if same is True:
                partial_shit_dir.append_msg(temp_msg_dir)
                shit_vector = await partial_shit_dir.update_vector(
                    self.db, embedding_provider
                )
                shit_dir_need_check = partial_shit_dir
            elif same is False:
                partial_shit_dir.release_shit()
                new_partial_shit_dir = ShitDirectory.save_shit_temporarily(temp_msg_dir)
                shit_vector = await new_partial_shit_dir.insert_vector(
                    self.db, embedding_provider
                )
                shit_dir_need_check = new_partial_shit_dir
            else:
                partial_shit_dir.release_shit()
        else:
            is_shit = await classify(self.context, chat_provider_id, temp_msg_dir)
            if is_shit:
                new_partial_shit_dir = ShitDirectory.save_shit_temporarily(temp_msg_dir)
                shit_vector = await new_partial_shit_dir.insert_vector(
                    self.db, embedding_provider
                )
                shit_dir_need_check = new_partial_shit_dir

        if shit_dir_need_check and shit_vector:
            dup_shit_dir = await find_duplicate(
                self.context,
                chat_provider_id,
                rerank_provider,
                self.db,
                shit_dir_need_check,
                shit_vector,
            )
            if dup_shit_dir:
                reply = await generate_roast_reply(
                    self.context,
                    chat_provider_id,
                    original_dir=dup_shit_dir,
                    this_dir=shit_dir_need_check,
                )
                await event.send(
                    event.chain_result([At(qq=record.sender_id), Plain(reply)])
                )
            else:
                dup_shit_msg = await find_duplicate_msg(
                    self.context, chat_provider_id, shit_dir_need_check
                )
                if dup_shit_msg:
                    latest_msg_id = shit_dir_need_check.get_metadata()["msg_ids"][-1]
                    latest_msg_dir = MsgDirectory(
                        shit_dir_need_check.get_msg_dir(latest_msg_id)
                    )
                    reply = await generate_msg_roast_reply(
                        self.context,
                        chat_provider_id,
                        original_dir=dup_shit_msg,
                        this_dir=latest_msg_dir,
                    )
                    shit_dir_need_check.pop_msg()
                    await shit_dir_need_check.update_vector(self.db, embedding_provider)
                    await event.send(
                        event.chain_result([At(qq=record.sender_id), Plain(reply)])
                    )

    async def terminate(self) -> None:
        await self.db.close()
        await super().terminate()
