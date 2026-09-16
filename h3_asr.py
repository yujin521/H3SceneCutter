# -*- coding: utf-8 -*-
"""
本地语音识别模块（faster-whisper）
==================================
从视频/音频中提取台词（ASR），完全本地运行，不依赖任何云服务。

模型目录约定：
  - exe 打包版：<exe所在目录>/models/whisper-small/
  - 源码运行版：本文件同级 models/whisper-small/
模型文件：model.bin + config.json + tokenizer.json + vocabulary.txt
"""

import sys
import threading
from pathlib import Path

_MODEL = None
_LOCK = threading.Lock()


def get_model_dir():
    if getattr(sys, "frozen", False):
        run_dir = Path(sys.executable).parent
    else:
        run_dir = Path(__file__).resolve().parent
    return run_dir / "models" / "whisper-small"


def load_model():
    """懒加载 whisper 模型（进程内只加载一次）。"""
    global _MODEL
    with _LOCK:
        if _MODEL is None:
            from faster_whisper import WhisperModel
            mdir = get_model_dir()
            if not (mdir / "model.bin").exists():
                raise FileNotFoundError(
                    f"未找到语音识别模型：{mdir}\n"
                    f"请确认工具目录下存在 models/whisper-small/model.bin")
            _MODEL = WhisperModel(str(mdir), device="cpu", compute_type="int8")
    return _MODEL


def transcribe_media(media_path):
    """识别视频或音频文件中的语音。

    Returns:
        [{start, end, text}, ...] 按时间排序，单位秒
    """
    model = load_model()
    segments, _info = model.transcribe(
        str(media_path), language="zh", vad_filter=True)
    result = []
    for seg in segments:
        text = seg.text.strip()
        if text:
            result.append({
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": text,
            })
    return result
