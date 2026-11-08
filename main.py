import os
import time

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path
import astrbot.api.message_components as Comp


class SponsorPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config or {}
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.enabled = bool(self.config.get("enabled", True))
        self.keyword_notice_enabled = bool(
            self.config.get("keyword_notice_enabled", True)
        )
        self.qr_commands_enabled = bool(self.config.get("qr_commands_enabled", True))
        self.mention_sender = bool(self.config.get("mention_sender", True))
        try:
            self.cooldown_seconds = max(
                0, min(300, int(self.config.get("cooldown_seconds", 10)))
            )
        except (TypeError, ValueError):
            self.cooldown_seconds = 10
        self.keyword = str(self.config.get("keyword", "赞助")).strip() or "赞助"
        self.llm_wake_prefixes = [
            prefix.strip()
            for prefix in str(self.config.get("llm_wake_prefixes", "萝卜")).split(",")
            if prefix.strip()
        ]
        self.wechat_command = (
            str(self.config.get("wechat_command", "赞助微信")).strip() or "赞助微信"
        )
        self.alipay_command = (
            str(self.config.get("alipay_command", "赞助支付宝")).strip()
            or "赞助支付宝"
        )
        self.custom_command = str(self.config.get("custom_command", "")).strip()
        self.notice_text = (
            str(
                self.config.get(
                    "notice_text", '请回复“赞助微信”或“赞助支付宝”'
                )
            ).strip()
            or '请回复“赞助微信”或“赞助支付宝”'
        )
        self.last_notice_time = {}
        self.image_replies = {
            self.wechat_command: self._resolve_image_path("wechat_image_path", ""),
            self.alipay_command: self._resolve_image_path("alipay_image_path", ""),
        }
        custom_image_path = self._resolve_image_path("custom_image_path", "")
        if self.custom_command and custom_image_path:
            if self.custom_command in self.image_replies:
                logger.warning(f"自定义指令与现有指令重复，已忽略: {self.custom_command}")
            else:
                self.image_replies[self.custom_command] = custom_image_path
        logger.info("赞助回复插件已加载")

    @staticmethod
    def _normalize_command(message: str) -> str:
        """兼容群聊里常见的空格和结尾标点，但不做模糊关键词匹配。"""
        return message.strip().rstrip("。！!？?，, ").replace(" ", "")

    def _resolve_image_path(self, config_key: str, default_name: str) -> str:
        configured_value = self.config.get(config_key, "")
        if isinstance(configured_value, list):
            configured = next(
                (str(item).strip() for item in configured_value if str(item).strip()),
                "",
            )
        else:
            configured = str(configured_value).strip()

        if configured.startswith("files/"):
            return os.path.abspath(
                os.path.join(
                    get_astrbot_plugin_data_path(),
                    "astrbot_plugin_sponsor",
                    configured,
                )
            )

        if not configured and not default_name:
            return ""

        image_path = configured or default_name
        if not os.path.isabs(image_path):
            image_path = os.path.join(self.plugin_dir, image_path)
        return os.path.abspath(image_path)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """完整赞助指令发二维码，普通提及赞助只@提示。"""
        if not self.enabled:
            return
        original = event.message_str.strip()
        if not original or event.get_sender_id() == event.get_self_id():
            return

        # 群聊中发给机器人的消息应由主对话处理，不能被赞助提示截断。
        if event.get_group_id() and (
            event.is_at_or_wake_command
            or any(original.startswith(prefix) for prefix in self.llm_wake_prefixes)
        ):
            return

        command = self._normalize_command(original)
        if self.qr_commands_enabled and command in self.image_replies:
            image_path = self.image_replies[command]
            if not os.path.isfile(image_path):
                logger.warning("赞助图片不存在，指令=%s，路径=%s", command, image_path)
                yield event.plain_result("赞助图片暂未配置，请联系管理员。")
                return

            # 二维码必须单独发送。部分 OneBot/NapCat 环境会在“@ + 图片”混合消息上超时。
            yield event.chain_result([
                Comp.Image.fromFileSystem(path=image_path)
            ])
            return

        if not self.keyword_notice_enabled or self.keyword not in original:
            return

        group_id = event.get_group_id()
        cooldown_key = str(group_id or event.get_sender_id())
        now = time.monotonic()
        if (
            self.cooldown_seconds > 0
            and now - self.last_notice_time.get(cooldown_key, 0)
            < self.cooldown_seconds
        ):
            return
        self.last_notice_time[cooldown_key] = now

        if group_id and self.mention_sender:
            yield event.chain_result([
                Comp.At(qq=event.get_sender_id()),
                Comp.Plain(self.notice_text),
            ])
        else:
            yield event.plain_result(self.notice_text)

    async def terminate(self):
        logger.info("赞助回复插件已卸载")
