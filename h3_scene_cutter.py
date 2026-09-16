#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
H3 镜头切帧核心模块 + 命令行入口
=================================
功能：
  1. 自动识别视频中的镜头切变点（硬切）
  2. 截取每个新镜头的首帧图片，输出 cut_001_first.jpg / cut_002_first.jpg ...
  3. 输出 scenes_info.json 时间轴（镜头号/起止帧/起止时间/时长）

命令行用法：
  python h3_scene_cutter.py 视频路径 [--out 输出目录] [--threshold 27] [--min-scene-len 0.5]

作为模块导入（Web 版使用）：
  from h3_scene_cutter import detect_and_extract
  scenes = detect_and_extract(video_path, out_dir, threshold=27.0, min_scene_len=0.5)
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import cv2
    from scenedetect import open_video, SceneManager
    from scenedetect.detectors import ContentDetector
except ImportError as e:
    sys.exit(f"缺少依赖: {e}\n请先运行: python -m pip install scenedetect opencv-python")


def detect_and_extract(video_path, out_dir, threshold=27.0, min_scene_len=0.5):
    """检测视频镜头切变并提取每个镜头首帧。

    Args:
        video_path: 视频文件路径
        out_dir: 输出目录（首帧图片 + scenes_info.json 写到这里）
        threshold: 镜头检测灵敏度 0~100，越大越不易误切
        min_scene_len: 最小镜头时长（秒），过滤抖动误检

    Returns:
        scenes: 镜头列表，每项含 index/start_frame/end_frame/start_time_s/
                end_time_s/duration_s/first_frame
    """
    video_path = Path(video_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    video = open_video(str(video_path))
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold, min_scene_len=min_scene_len))
    sm.detect_scenes(video)
    scene_list = sm.get_scene_list()

    scenes = []
    for i, (start_tc, end_tc) in enumerate(scene_list, start=1):
        frame_num = start_tc.frame_num
        video.seek(frame_num)
        frame = video.read()
        if frame is False or frame is None:
            continue
        img_name = f"cut_{i:03d}_first.jpg"
        cv2.imwrite(str(out_dir / img_name), frame)
        scenes.append({
            "index": i,
            "start_frame": frame_num,
            "end_frame": end_tc.frame_num,
            "start_time_s": round(start_tc.seconds, 3),
            "end_time_s": round(end_tc.seconds, 3),
            "duration_s": round(end_tc.seconds - start_tc.seconds, 3),
            "first_frame": img_name,
        })

    video.reset()  # 释放底层资源

    if scenes:
        info_path = out_dir / "scenes_info.json"
        info_path.write_text(
            json.dumps({"video": str(video_path), "fps": float(scene_list[0][0].framerate),
                        "scene_count": len(scenes), "scenes": scenes},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
    return scenes


def build_prompt_template(scenes):
    """按约定 demo 格式生成 H3 提示词模板文本。"""
    lines = []
    for s in scenes:
        lines.append(f"🎬 图 {s['index']}：镜头{s['index']}（景别待填）")
        lines.append("detailed_description:")
        lines.append("【画面描述】：【待AI填写：只写画面里有什么、在哪里——"
                     "人物/物体/位置/服饰/动作/环境/光影，不写机位运镜】")
        lines.append(f"【台词】 At 0s, 【角色】用【语气】说道："
                     f"<d>[Audio {s['index']}][Chinese][语气] 【台词内容】</d>")
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(
        description="检测视频镜头切变，保存每个镜头首帧，并生成 H3 提示词模板"
    )
    ap.add_argument("video", help="输入视频文件路径（mp4/mov/avi 等）")
    ap.add_argument("--out", "-o", default="h3_cut_output", help="输出目录（默认 h3_cut_output）")
    ap.add_argument("--threshold", type=float, default=27.0,
                    help="镜头检测灵敏度 0~100，越大越不易误切（默认 27）")
    ap.add_argument("--min-scene-len", type=float, default=0.5,
                    help="最小镜头时长秒数，过滤误检（默认 0.5）")
    args = ap.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        sys.exit(f"视频文件不存在: {video_path}")

    out_dir = Path(args.out)
    scenes = detect_and_extract(video_path, out_dir, args.threshold, args.min_scene_len)
    if not scenes:
        sys.exit("未检测到任何镜头切变。可降低 --threshold（如 15）重试。")

    print(f"视频帧率检测完成，共 {len(scenes)} 个镜头：\n")
    for s in scenes:
        print(f"[{s['index']:03d}] {s['start_time_s']:7.3f}s -> {s['end_time_s']:7.3f}s  "
              f"({s['duration_s']:.2f}s)  首帧: {s['first_frame']}")

    # 提示词模板
    tmpl_path = out_dir / "h3_prompts_template.txt"
    tmpl_path.write_text(build_prompt_template(scenes), encoding="utf-8")

    print(f"\n✅ 完成！共 {len(scenes)} 个镜头")
    print(f"   首帧图片: {out_dir}/cut_*_first.jpg")
    print(f"   时间轴:   {out_dir}/scenes_info.json")
    print(f"   提示词模板: {tmpl_path}")


if __name__ == "__main__":
    main()
