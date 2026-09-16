#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
H3 镜头切帧 Web 工具 - 后端服务
================================
启动后自动打开浏览器：http://127.0.0.1:8787

功能：
  - 上传视频，后台自动检测镜头切变并提取每个镜头首帧
  - 网页查看首帧大图、镜头时间轴、播放原视频
  - 编辑每个镜头的 H3 提示词（标题/景别/画面描述/台词/角色/语气）
  - 忽略误检镜头、导出最终 H3 提示词脚本（txt / json）

运行：
  python h3_scene_web.py [--port 8787] [--no-browser]
"""

import argparse
import json
import os
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

from h3_scene_cutter import detect_and_extract

# exe 打包（PyInstaller）时：static 资源在 _MEIPASS 临时目录，数据目录在 exe 旁边
if getattr(sys, "frozen", False):
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    RUN_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent
    RUN_DIR = BASE_DIR

DATA_DIR = RUN_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
RESULT_DIR = DATA_DIR / "results"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm", ".m4v", ".ts"}
app = Flask(__name__, static_folder="static", static_url_path="/")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB

TASKS = {}  # task_id -> {status, video_name, video_path, result_dir, scenes, error, created}


def _load_tasks():
    """启动时恢复已有任务状态（切帧结果落盘在 results/<tid>/task_state.json）。"""
    for d in RESULT_DIR.iterdir():
        state_path = d / "task_state.json"
        if d.is_dir() and state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                state["result_dir"] = str(d)
                TASKS[state["task_id"]] = state
            except Exception:
                continue


def _save_state(tid):
    TASKS[tid]["result_dir"] = str(RESULT_DIR / tid)
    (RESULT_DIR / tid / "task_state.json").write_text(
        json.dumps(TASKS[tid], ensure_ascii=False, indent=2), encoding="utf-8")


def _run_detect(tid, video_path, threshold, min_scene_len):
    """后台线程：切帧 + 初始化每个镜头的提示词字段。"""
    try:
        result_dir = RESULT_DIR / tid
        result_dir.mkdir(parents=True, exist_ok=True)
        scenes = detect_and_extract(video_path, result_dir, threshold, min_scene_len)
        for s in scenes:
            s.update({
                "hidden": False,
                "title": f"镜头{s['index']}",
                "shot_size": "",
                "visual": "",
                "dialogue": "",
                "speaker": "",
                "tone": "",
                "audio_index": s["index"],
            })
        TASKS[tid]["scenes"] = scenes
        TASKS[tid]["status"] = "done" if scenes else "empty"
        if not scenes:
            TASKS[tid]["error"] = "未检测到镜头切变，请调低灵敏度（如 15）或换更小的 min-scene-len 重试"
    except Exception as e:
        TASKS[tid]["status"] = "error"
        TASKS[tid]["error"] = str(e)
    finally:
        _save_state(tid)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/upload")
def upload():
    f = request.files.get("video")
    if not f or not f.filename:
        return jsonify({"error": "未选择文件"}), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": f"不支持的视频格式：{ext}，支持 {sorted(ALLOWED_EXT)}"}), 400

    tid = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    video_path = UPLOAD_DIR / f"{tid}{ext}"
    f.save(str(video_path))

    threshold = request.form.get("threshold", type=float, default=27.0)
    min_scene_len = request.form.get("min_scene_len", type=float, default=0.5)

    TASKS[tid] = {
        "task_id": tid,
        "status": "processing",
        "video_name": f.filename,
        "video_path": str(video_path),
        "scenes": [],
        "error": None,
        "asr_status": "none",
        "asr_error": None,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    threading.Thread(target=_run_detect, args=(tid, video_path, threshold, min_scene_len),
                     daemon=True).start()
    return jsonify({"task_id": tid})


def _run_asr(tid):
    """后台线程：本地语音识别，台词按时间戳归入对应镜头。"""
    try:
        from h3_asr import transcribe_media
        t = TASKS[tid]
        segments = transcribe_media(t["video_path"])
        scenes = t["scenes"]
        assigned = 0
        for seg in segments:
            ts = seg["start"]
            target = None
            for s in scenes:
                if s["start_time_s"] <= ts < s["end_time_s"]:
                    target = s
                    break
            if target is None and scenes:
                # 台词落在镜头边界外：归入时间中点最近的镜头
                target = min(scenes, key=lambda s: abs(ts - (s["start_time_s"] + s["end_time_s"]) / 2))
            if target is not None:
                if target["dialogue"]:
                    target["dialogue"] += "，" + seg["text"]
                else:
                    target["dialogue"] = seg["text"]
                assigned += 1
        t["asr_segments"] = segments
        t["asr_status"] = "done" if assigned else "empty"
        if not assigned:
            t["asr_error"] = "未识别到语音（视频可能没有音轨或无人声）"
    except Exception as e:
        t["asr_status"] = "error"
        t["asr_error"] = str(e)
    finally:
        _save_state(tid)


@app.post("/api/task/<tid>/asr")
def run_asr(tid):
    """对已切帧任务启动台词提取（本地语音识别）。"""
    t = TASKS.get(tid)
    if not t or t["status"] != "done":
        return jsonify({"error": "任务不可用"}), 400
    if t.get("asr_status") == "processing":
        return jsonify({"error": "台词提取进行中"}), 400
    t["asr_status"] = "processing"
    t["asr_error"] = None
    _save_state(tid)
    threading.Thread(target=_run_asr, args=(tid,), daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/tasks")
def task_list():
    """历史切帧记录列表（按创建时间倒序）。"""
    items = []
    for tid, t in TASKS.items():
        if not (RESULT_DIR / tid).exists():
            continue
        items.append({
            "task_id": tid,
            "video_name": t.get("video_name", "未知视频"),
            "created": t.get("created", ""),
            "status": t.get("status", ""),
            "scene_count": len(t.get("scenes", [])),
            "error": t.get("error"),
        })
    items.sort(key=lambda x: x["created"], reverse=True)
    return jsonify({"tasks": items})


@app.get("/api/task/<tid>")
def task_status(tid):
    t = TASKS.get(tid)
    if not t:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify({
        "status": t["status"],
        "video_name": t["video_name"],
        "video_url": f"/api/task/{tid}/video",
        "scenes": t["scenes"],
        "error": t["error"],
        "asr_status": t.get("asr_status", "none"),
        "asr_error": t.get("asr_error"),
        "created": t.get("created"),
    })


@app.get("/api/task/<tid>/video")
def task_video(tid):
    t = TASKS.get(tid)
    if not t:
        return jsonify({"error": "任务不存在"}), 404
    return send_file(t["video_path"])


@app.get("/api/task/<tid>/frame/<name>")
def task_frame(tid, name):
    t = TASKS.get(tid)
    if not t:
        return jsonify({"error": "任务不存在"}), 404
    return send_file(Path(t["result_dir"]) / name)


@app.post("/api/task/<tid>/scene/<int:idx>")
def update_scene(tid, idx):
    t = TASKS.get(tid)
    if not t or t["status"] != "done":
        return jsonify({"error": "任务不可编辑"}), 400
    data = request.get_json(silent=True) or {}
    for s in t["scenes"]:
        if s["index"] == idx:
            for key in ("title", "shot_size", "visual", "dialogue", "speaker", "tone",
                        "hidden", "audio_index"):
                if key in data:
                    s[key] = data[key]
            _save_state(tid)
            return jsonify({"ok": True, "scene": s})
    return jsonify({"error": "镜头不存在"}), 404


@app.get("/api/task/<tid>/export")
def export(tid):
    t = TASKS.get(tid)
    if not t or t["status"] != "done":
        return jsonify({"error": "任务不可导出"}), 400
    fmt = request.args.get("format", "txt")
    visible = [s for s in t["scenes"] if not s.get("hidden")]

    if fmt == "json":
        return jsonify({
            "video": t["video_name"],
            "scene_count": len(visible),
            "scenes": visible,
        })

    lines = []
    for i, s in enumerate(visible, start=1):
        title = s.get("title") or f"镜头{s['index']}"
        shot = f"（{s['shot_size']}）" if s.get("shot_size") else ""
        visual = s.get("visual", "").strip() or "【待填写：只写画面里有什么、在哪里——人物/物体/位置/服饰/动作/环境/光影】"
        speaker = s.get("speaker", "").strip() or "【角色】"
        tone = s.get("tone", "").strip() or "【语气】"
        dialogue = s.get("dialogue", "").strip() or "【台词内容】"
        lines.append(f"🎬 图 {i}：{title}{shot}")
        lines.append("detailed_description:")
        lines.append(f"【画面描述】：{visual}")
        if s.get("tone", "").strip():
            lines.append(f"【台词】 At 0s, {speaker}用{tone}的语气说道："
                         f"<d>[Audio {s.get('audio_index', i)}][Chinese][{tone}] {dialogue}</d>")
        else:
            lines.append(f"【台词】 At 0s, {speaker}用{tone}说道："
                         f"<d>[Audio {s.get('audio_index', i)}][Chinese][{tone}] {dialogue}</d>")
        lines.append("")
    text = "\n".join(lines)

    if fmt == "download":
        resp = app.response_class(text, mimetype="text/plain; charset=utf-8")
        resp.headers["Content-Disposition"] = f"attachment; filename=h3_prompts_{tid}.txt"
        return resp
    return app.response_class(text, mimetype="text/plain; charset=utf-8")


def main():
    ap = argparse.ArgumentParser(description="H3 镜头切帧 Web 工具")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-browser", action="store_true", help="启动时不自动打开浏览器")
    args = ap.parse_args()

    _load_tasks()
    url = f"http://127.0.0.1:{args.port}"

    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    print(f"\n  🎬 H3 镜头切帧工具已启动: {url}")
    print(f"  上传目录: {UPLOAD_DIR}")
    print(f"  结果目录: {RESULT_DIR}")
    print("  按 Ctrl+C 停止服务\n")

    app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
