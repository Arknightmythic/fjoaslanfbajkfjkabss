import json
import time
import httpx
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, "C:/Users/valer/synchrono-chatbot")
load_dotenv(dotenv_path="C:/Users/valer/synchrono-chatbot/.env")
from src.databases.connectors.mysql import MySQLConnector

db = MySQLConnector(
    host=os.getenv("DB_HOST", "127.0.0.1"),
    port=int(os.getenv("DB_PORT", "9030")),
    database=os.getenv("DB_NAME", "synchrono"),
    username=os.getenv("DB_USER", "synchrono_readonly"),
    password=os.getenv("DB_PASSWORD", "change_me_local"),
)

BASE_URL = "http://127.0.0.1:8001/chat"

def query_chat(question: str, thread_id: str, timeout: float = 120.0) -> dict:
    t0 = time.time()
    tools_called = []
    tool_args = []
    answer = ""
    error = None

    try:
        with httpx.stream(
            "POST",
            BASE_URL,
            json={"user_id": "extensive-eval", "thread_id": thread_id, "question": question},
            headers={"Accept": "text/event-stream"},
            timeout=timeout,
        ) as resp:
            if resp.status_code != 200:
                return {
                    "question": question,
                    "thread_id": thread_id,
                    "status_code": resp.status_code,
                    "error": f"HTTP {resp.status_code}",
                    "duration": round(time.time() - t0, 2),
                    "tools": [],
                    "tool_args": [],
                    "answer": "",
                }

            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                try:
                    event = json.loads(data_str)
                    step = event.get("step")
                    if step == "AIMessageChunk":
                        if event.get("tool_calls"):
                            for tc in event["tool_calls"]:
                                tools_called.append(tc.get("name"))
                                tool_args.append(tc.get("args"))
                        elif event.get("content"):
                            answer += event.get("content")
                    elif step == "ERROR":
                        error = event.get("content")
                except Exception:
                    pass
    except Exception as exc:
        error = str(exc)

    duration = round(time.time() - t0, 2)
    return {
        "question": question,
        "thread_id": thread_id,
        "duration": duration,
        "tools": tools_called,
        "tool_args": tool_args,
        "answer": answer,
        "error": error,
    }

TASK1_CASES = [
    {"id": "SEM-01", "q": "Berapa jumlah job grading hari ini?"},
    {"id": "SEM-02", "q": "Berapa job grading yang selesai (COMPLETED) hari ini?"},
    {"id": "SEM-03", "q": "Berapa job grading yang gagal (FAILED) minggu ini?"},
    {"id": "SEM-04", "q": "Berapa jumlah file unik yang sudah digrading (berdasarkan file_id dan filename)?"},
    {"id": "SEM-05", "q": "Berapa total data incoming pemadanan (matching) secara keseluruhan?"},
    {"id": "SEM-06", "q": "Berapa perbandingan jumlah auto match dan review pada proses pemadanan?"},
    {"id": "SEM-07", "q": "Bagaimana distribusi status job pemadanan (matching jobs) saat ini?"},
    {"id": "SEM-08", "q": "Berapa jumlah job grading untuk masing-masing institusi?"},
    {"id": "SEM-09", "q": "Berapa total baris data anomali dan data bersih pada tabel anomali K/L?"},
    {"id": "SEM-10", "q": "Tampilkan tingkat anomali (anomaly rate) berdasarkan jenis anomali (anomaly type)."},
    {"id": "SEM-11", "q": "Berapa jumlah batch sinkronisasi dan berapa yang sudah DONE bulan ini?"},
    {"id": "SEM-12", "q": "Berapa jumlah batch part berdasarkan statusnya?"},
    {"id": "SEM-13", "q": "Tampilkan tren harian jumlah job grading dalam 7 hari terakhir."},
    {"id": "SEM-14", "q": "Berapa job matching yang selesai (COMPLETED) minggu ini?"},
    {"id": "SEM-15", "q": "Berapa jumlah kasus conflict dan unmatch pada proses matching?"},
    {"id": "SEM-16", "q": "Berapa total baris data K/L untuk institusi Kementerian Sosial?"},
    {"id": "SEM-17", "q": "Berapa total baris data (row count) pada job grading hari ini?"},
    {"id": "SEM-18", "q": "Berapa job grading yang berstatus CANCELLED sepanjang waktu?"},
    {"id": "SEM-19", "q": "Berapa jumlah job matching yang saat ini sedang berjalan (matching/running)?"},
    {"id": "SEM-20", "q": "Berapa total baris data (batch row count) dari batch yang berhasil disinkronisasi?"},
]

def run_task1():
    print("=== STARTING TASK 1: SEMANTIC LAYER (20 CASES) ===")
    results = []
    for case in TASK1_CASES:
        cid = case["id"]
        q = case["q"]
        print(f"[{cid}] Running: {q} ...", end=" ", flush=True)
        res = query_chat(q, thread_id=f"thread-{cid}")
        tool_used = res["tools"][0] if res["tools"] else "NONE"
        is_semantic = "query_metrics" in res["tools"]
        print(f"Done in {res['duration']}s (Tool: {res['tools']}, Semantic: {is_semantic})")
        results.append({
            "id": cid,
            "question": q,
            "duration": res["duration"],
            "tools": res["tools"],
            "tool_args": res["tool_args"],
            "is_semantic": is_semantic,
            "answer_preview": res["answer"][:180].replace("\n", " "),
            "full_answer": res["answer"],
            "error": res["error"],
        })
    with open("C:/Users/valer/AppData/Local/Temp/opencode/synchrono-api-tests/task1_semantic_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("Task 1 finished and saved.")

if __name__ == "__main__":
    run_task1()
