"""Provider metadata shared by the API and the beginner-facing settings UI."""
from __future__ import annotations

LLM_PROVIDERS = {
    'deepseek': {
        'id': 'deepseek', 'name': 'DeepSeek', 'description': '推荐 · 只需填写 API Key',
        'base_url': 'https://api.deepseek.com', 'model': 'deepseek-v4-flash',
        'key_url': 'https://platform.deepseek.com/api_keys', 'type': 'openai-compatible',
    },
    'custom': {
        'id': 'custom', 'name': '自定义 · OpenAI 兼容', 'description': '适合已有模型服务的高级用户',
        'type': 'openai-compatible',
    },
}

BROLL_PROVIDERS = {
    'pexels': {
        'id': 'pexels', 'name': 'Pexels', 'description': '推荐 · 横屏库存视频',
        'key_url': 'https://www.pexels.com/api/new/',
    },
    'pixabay': {
        'id': 'pixabay', 'name': 'Pixabay', 'description': '备用 · 库存视频',
        'key_url': 'https://pixabay.com/api/docs/',
    },
}

AROLL_MODES = {
    'latentsync': {
        'id': 'latentsync', 'name': '高质量本地 · LatentSync 1.6',
        'short_name': 'LatentSync 1.6 · 高质量',
        'description': '本地高质量口型，适合 RTX 2080 Ti 22GB；速度较慢',
    },
    'autodl_h3': {
        'id': 'autodl_h3', 'name': '云端高质量 · MiniMax H3 自动对口型', 'short_name': 'H3 · 云端口型',
        'description': '上传人物图片和对应原音频到 AutoDL，生成带自然表情与动作的 A-roll',
    },
    'infinitetalk': {
        'id': 'infinitetalk', 'name': '单人影片 · InfiniteTalk Q8', 'short_name': 'InfiniteTalk · 单人',
        'description': '使用已有 ComfyUI，由人物图片和原音频生成口型、表情与细微动作',
    },
    'wav2lip': {
        'id': 'wav2lip', 'name': '轻量本地 · Wav2Lip', 'short_name': 'Wav2Lip · 轻量',
        'description': '速度快、安装体积较小，适合低配置设备', 'license': '仅限个人 / 研究 / 非商业用途',
    },
    'musetalk': {
        'id': 'musetalk', 'name': '高质量快速本地 · MuseTalk 1.5', 'short_name': 'MuseTalk 1.5 · 高质量',
        'description': '支持 FP32、官方下巴解析融合与低压缩中间文件',
    },
    'custom': {
        'id': 'custom', 'name': '自定义工作流', 'short_name': '自定义工作流',
        'description': '连接 ComfyUI 或您自己的在线视频服务',
    },
}

AROLL_CUSTOM_TYPES = {
    'comfyui': {'id': 'comfyui', 'name': 'ComfyUI', 'short_name': 'ComfyUI · 自定义'},
    'external_api': {'id': 'external_api', 'name': '在线 API', 'short_name': '在线 API'},
}


def public_catalog():
    """Return display metadata only; fixed endpoints remain server-owned."""
    def clean(items):
        return [{k: v for k, v in item.items() if k not in ('base_url', 'model')} for item in items.values()]
    return {
        'llm': clean(LLM_PROVIDERS),
        'broll': clean(BROLL_PROVIDERS),
        'aroll': clean(AROLL_MODES),
        'aroll_custom_types': clean(AROLL_CUSTOM_TYPES),
    }
