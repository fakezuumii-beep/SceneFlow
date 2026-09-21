"""Prompt builders shared by the H3 engine.

A-roll and generated-scene prompts intentionally live on separate paths even
though both submit work through the same AutoDL MiniMax H3 engine.
"""
from __future__ import annotations


H3_PROMPTS = {
    'steady': ('单人播客主持人正对镜头自然说话，口型严格跟随参考音频。全程固定机位、一个连续长镜头，'
               '不要切镜，不要变焦，不要推拉摇移，不要改变景别。保持参考图中的同一人物、背景、桌面、'
               '麦克风、灯光、陈设、服装和发型，只允许自然的嘴部动作、眨眼和极轻微面部表情。'),
    'restrained': ('单人播客主持人正对镜头自然说话，口型严格跟随参考音频。以稳定长镜头为主，整段最多一次'
                   '自然的中景、中近景或近景切换，禁止连续切镜、快速蒙太奇和推拉摇移。保持参考图中的同一人物、'
                   '背景、桌面、麦克风、灯光、陈设、服装和发型。'),
    'free': ('单人播客主持人正对镜头自然说话，口型严格跟随参考音频。可在中景、中近景和近景之间自然切换，'
             '保持参考图中的同一人物、背景、桌面、麦克风、灯光、陈设、服装和发型。'),
}


class ArollPromptBuilder:
    def build(self, settings):
        style = str(settings.get('aroll_autodl_cut_style') or 'steady')
        return H3_PROMPTS.get(style, H3_PROMPTS['steady'])
