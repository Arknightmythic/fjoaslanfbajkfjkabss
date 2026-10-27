import json
import time
import httpx
import os
import sys

BASE_URL = "http://127.0.0.1:8001/chat"

TURNS = [
    {"turn": 1, "q": "Tampilkan status penilaian berkas (grading jobs) secara umum saat ini."},
    {"turn": 2, "q": "Dari data status tadi, berapa yang sudah COMPLETED dan berapa yang FAILED?"},
    {"turn": 3, "q": "Dari yang COMPLETED tadi, sebutkan 3 nama file fisik yang ada di database."},
    {"turn": 4, "q": "Fokus ke berkas 'uji_master_A.csv' tadi. Berapa skor mutunya dan apa huruf gradenya?"},
    {"turn": 5, "q": "Mengapa berkas tersebut bisa dapat skor 100? Bagaimana kelengkapan atribut identitasnya?"},
    {"turn": 6, "q": "Sekarang bandingkan dengan 'uji_master_B.csv'. Berapa skor mutu dan grade dari uji_master_B?"},
    {"turn": 7, "q": "Antara uji_master_A dan uji_master_B tadi, mana yang memiliki jumlah baris data lebih banyak?"},
    {"turn": 8, "q": "Siapa institusi pengunggah kedua berkas tersebut?"},
    {"turn": 9, "q": "Apakah kedua berkas yang kita bahas tadi sudah pernah dijalankan proses pemadanan (matching)?"},
    {"turn": 10, "q": "Sebutkan kembali semua nama file dan skor yang tadi sudah kita bahas dari awal percakapan sampai sekarang."},
    {"turn": 11, "q": "Berapa total baris data jika kedua berkas tersebut digabungkan?"},
    {"turn": 12, "q": "Di antara kedua file tadi, apakah ada yang terdeteksi anomali pada datanya?"},
    {"turn": 13, "q": "Kembali ke pertanyaan pertama tadi, berapa tadi total job grading yang tercatat di awal obrolan?"},
    {"turn": 14, "q": "Dari total job grading awal tersebut, berapa persentase yang berstatus COMPLETED?"},
    {"turn": 15, "q": "Ringkas seluruh temuan dari analisis kita dari nomor 1 sampai sekarang dalam sebuah tabel ringkas."},
]

def run_task3():
    print("=== STARTING TASK 3: MULTI-TURN CHAIN STRESS TEST (15 TURNS) ===")
    thread_id = f"stress-chain-{int(time.time())}"
    history = []

    for item in TURNS:
        t_num = item["turn"]
        q = item["q"]
        print(f"\n[TURN {t_num:02d}] User: {q}")
        t0 = time.time()
        tools_called = []
        answer = ""

        with httpx.stream(
            "POST",
            BASE_URL,
            json={"user_id": "eval-tester", "thread_id": thread_id, "question": q},
            headers={"Accept": "text/event-stream"},
            timeout=120.0,
        ) as resp:
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
                        elif event.get("content"):
                            answer += event.get("content")
                except Exception:
                    pass

        dur = round(time.time() - t0, 2)
        print(f"[{dur}s | Tools: {tools_called}] AI: {answer[:140].replace(chr(10), ' ')}...")
        history.append({
            "turn": t_num,
            "question": q,
            "duration": dur,
            "tools": tools_called,
            "answer": answer,
        })

    with open("C:/Users/valer/AppData/Local/Temp/opencode/synchrono-api-tests/task3_multiturn_results.json", "w", encoding="utf-8") as f:
        json.dump({"thread_id": thread_id, "turns": history}, f, indent=2, ensure_ascii=False)
    print("\nTask 3 finished and saved.")

if __name__ == "__main__":
    run_task3()
