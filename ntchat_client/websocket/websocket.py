import asyncio
import json
from typing import Callable

import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.legacy.client import WebSocketClientProtocol

from ntchat_client.config import Config
from ntchat_client.log import logger
from ntchat_client.model import WsRequest, WsResponse
from ntchat_client.utils import escape_tag
from ntchat_client.wechat import get_wechat_client

ws_manager: "WsManager"
"""全局ws管理端"""


async def websocket_init(config: Config) -> None:
    """初始化ws连接"""
    global ws_manager
    logger.info("<m>websocket</m> - 正在初始化websocket管理器...")
    wechat_client = get_wechat_client()
    self_id = wechat_client.self_id
    ws_manager = WsManager(self_id, config)
    ws_manager.message_handler = wechat_client.handle_ws_api
    wechat_client.ws_message_handler = ws_manager.send_message
    logger.success("<m>websocket</m> - <g>websocket管理器初始化完成...</g>")
    if config.ws_address != "":
        asyncio.create_task(ws_manager.connect())


async def websocket_shutdown() -> None:
    """关闭websocket"""
    global ws_manager
    if not ws_manager.closed:
        await ws_manager.ws_client.close()


class WsManager:
    """ws连接管理"""

    ws_adress: str
    """ws链接地址"""
    headers: dict
    """连接认证头"""
    ws_client: WebSocketClientProtocol = None
    """ws连接实例"""
    message_handler: Callable[..., WsResponse] = None
    """ws消息处理函数"""

    @property
    def closed(self) -> bool:
        """是否已关闭"""
        if self.ws_client is None:
            return True
        return self.ws_client.closed

    def __init__(self, self_id: str, config: Config) -> None:
        self.ws_adress = config.ws_address
        self.headers = {"X-Self-ID": self_id, "access_token": config.access_token}

    async def connect(self) -> None:
        """连接ws服务"""
        while True:
            try:
                logger.info(f"<m>websocket</m> - 正在连接到：<g>{self.ws_adress}</g>")
                self.ws_client = await websockets.connect(
                    uri=self.ws_adress,
                    extra_headers=self.headers,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                )
                asyncio.create_task(self._task())
                logger.success("<m>websocket</m> - <g>ws已成功连接！</g>")
                return
            except Exception as e:
                logger.error(f"<m>websocket</m> - 连接到ws地址发生错误：<r>{str(e)}</r>")
                await asyncio.sleep(2)

    async def _task(self) -> None:
        """循环等待接收任务"""
        try:
            while True:
                msg = await self.ws_client.recv()
                log_msg = escape_tag(msg)
                if len(log_msg) > 100:
                    log_msg = log_msg[:100]
                logger.success(f"<m>websocket</m> - <g>收到ws消息：</g>{log_msg}")
                msg = json.loads(msg)
                msg = WsRequest.parse_obj(msg)
                if self.message_handler:
                    data = self.message_handler(msg)
                    asyncio.create_task(self.send_message(data.dict()))

        except ConnectionClosedOK:
            logger.success("<m>websocket</m> - <g>ws链接已主动关闭...</g>")
            self.ws_client = None

        except ConnectionClosedError as e:
            logger.error(f"<m>websocket</m> - ws链接异常关闭：<r>{e.reason}</r>")
            # 自启动
            self.ws_client = None
            await self.connect()

    async def send_message(self, message: dict) -> None:
        """发送ws消息"""
        if not self.closed:
            data = json.dumps(message, ensure_ascii=False)
            logger.debug(f"<m>websocket</m> - <e>向ws发送消息：</e>{escape_tag(data)}")
            await self.ws_client.send(data)
