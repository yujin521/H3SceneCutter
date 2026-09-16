# -*- coding: utf-8 -*-
"""端到端测试：上传→切帧→中文编辑→忽略→导出"""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8787"


def upload(video_path):
    boundary = "----h3testboundary"
    data = open(video_path, "rb").read()
    head = (f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="video"; filename="test.mp4"\r\n'
            "Content-Type: video/mp4\r\n\r\n").encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/upload", data=head + data + tail,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.loads(urllib.request.urlopen(req).read().decode("utf-8"))["task_id"]


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path).read().decode("utf-8"))


def post(path, obj):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req).read().decode("utf-8"))


tid = upload(r"C:\Users\Administrator\Doubao\chats\2026-09-16\new-chat\test_video.mp4")
print("task_id:", tid)

for _ in range(30):
    time.sleep(1)
    st = get(f"/api/task/{tid}")
    if st["status"] != "processing":
        print("status:", st["status"], "| scenes:", len(st["scenes"]))
        break

r = post(f"/api/task/{tid}/scene/1", {
    "title": "女方起疑", "shot_size": "双人中景",
    "visual": "夜晚卧室，左侧男生穿浅蓝条纹睡衣看手机，右侧女生穿白色蕾丝吊带侧身说话",
    "speaker": "女生", "tone": "带着疑问",
    "dialogue": "你们男的是不是都喜欢年轻的？", "audio_index": 1})
print("编辑镜头1:", r["scene"]["title"], "|", r["scene"]["visual"][:18], "|", r["scene"]["dialogue"])

r = post(f"/api/task/{tid}/scene/3", {"hidden": True})
print("忽略镜头3:", r["scene"]["hidden"])

txt = urllib.request.urlopen(f"{BASE}/api/task/{tid}/export?format=download").read().decode("utf-8")
print("===== 导出txt =====")
print(txt)
