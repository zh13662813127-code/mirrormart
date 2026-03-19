"""平台环境插件包。"""

from mirrormart.platforms.douyin import DouyinEnvironment
from mirrormart.platforms.taobao import TaobaoEnvironment
from mirrormart.platforms.weibo import WeiboEnvironment
from mirrormart.platforms.xiaohongshu import XiaohongshuEnvironment

__all__ = [
    "DouyinEnvironment",
    "TaobaoEnvironment",
    "WeiboEnvironment",
    "XiaohongshuEnvironment",
]
