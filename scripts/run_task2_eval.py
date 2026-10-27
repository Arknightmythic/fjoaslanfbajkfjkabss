import json
import time
import httpx
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, "C:/Users/valer/synchrono-chatbot")
load_dotenv(dotenv_path="C:/Users/valer/synchrono-chatbot/.env")

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

TASK2_CASES = [
    {"id": "SQL-01", "q": "Mengapa job matching 'job_1793010193656_gzvwf' berstatus FAILED? Jelaskan alasan teknis dan waktu kegagalannya."},
    {"id": "SQL-02", "q": "Sebutkan pola-pola error yang menyebabkan proses pemadanan berstatus FAILED di tabel syncrono_portal_matching_jobs beserta frekuensinya."},
    {"id": "SQL-03", "q": "Untuk berkas 'uji_master_A.csv', berapa skor mutunya, apa huruf gradenya, dan berapa baris data yang dinilai?"},
    {"id": "SQL-04", "q": "Pada berkas 'kl_uji.csv' di syncrono_kl_records, berapa jumlah baris warga perempuan yang bersih dan berapa yang terdeteksi anomali?"},
    {"id": "SQL-05", "q": "Pada berkas 'uji_master_D.csv' di tabel syncrono_kl_enriched, sebutkan kode anomali (anomaly_codes) dan jenis anomali yang mendominasi data."},
    {"id": "SQL-06", "q": "Dari rekaman hasil pemadanan yang berstatus AUTO, berapa yang dicocokkan menggunakan PASS1_NIK_NAMA, PASS2_NAMA_TGL_IBU, dan SCORING?"},
    {"id": "SQL-07", "q": "Berapa jumlah rekaman yang masuk kategori status REVIEW di syncrono_portal_matching_results dan metode pemadanan apa yang digunakan?"},
    {"id": "SQL-08", "q": "Berapa jumlah kasus CONFLICT yang terjadi pada metode pemadanan PASS2_NAMA_TGL_IBU?"},
    {"id": "SQL-09", "q": "Berapa jumlah batch part dari batch yang berstatus CANCELLED pada tabel syncrono_service_batches?"},
    {"id": "SQL-10", "q": "Apa kriteria kelengkapan minimum untuk mendapatkan Grade A menurut tabel syncrono_service_grade_criteria?"},
    {"id": "SQL-11", "q": "Berapa rata-rata baris data per job grading (row_count) untuk berkas yang diunggah oleh 'Kementerian Kesehatan'?"},
    {"id": "SQL-12", "q": "Berapa jumlah catatan untuk masing-masing grade_letter (A, B, C, D, E, F) yang tercatat di tabel syncrono_service_grading_results?"},
    {"id": "SQL-13", "q": "Apakah berkas 'test_penduduk.csv' pernah digrading? Apa status grading terakhirnya dan berapa baris datanya?"},
    {"id": "SQL-14", "q": "Berapa jumlah job matching yang gagal karena kendala storage SeaweedFS timeout?"},
    {"id": "SQL-15", "q": "Apa rentang skor kualitas, label keparahan (severity), dan status can_proceed untuk Grade C di tabel syncrono_service_grade_bands?"},
    {"id": "SQL-16", "q": "Berapa total rekaman warga di syncrono_kl_records yang kolom jenis_kelamin-nya bernilai NULL atau kosong?"},
    {"id": "SQL-17", "q": "Sebutkan 3 nama file fisik yang memiliki total baris (row_count) terbanyak di syncrono_service_grading_jobs."},
    {"id": "SQL-18", "q": "Sebutkan contoh file_id yang sudah COMPLETED pada tahap grading namun belum memiliki catatan di syncrono_portal_matching_jobs."},
    {"id": "SQL-19", "q": "Tampilkan contoh teks reasoning (alasan) dari rekaman pemadanan yang berstatus REVIEW di syncrono_portal_matching_results."},
    {"id": "SQL-20", "q": "Berapa total data anomali dan persentase anomalinya untuk K/L Uji Integrasi pada syncrono_kl_records?"},
]

def run_task2():
    print("=== STARTING TASK 2: SELF-DIRECTED SQL / JOINS (20 CASES) ===")
    results = []
    for case in TASK2_CASES:
        cid = case["id"]
        q = case["q"]
        print(f"[{cid}] Running: {q} ...", end=" ", flush=True)
        res = query_chat(q, thread_id=f"thread-{cid}")
        has_run_query = "run_query" in res["tools"]
        print(f"Done in {res['duration']}s (Tools: {res['tools']}, Ran SQL: {has_run_query})")
        results.append({
            "id": cid,
            "question": q,
            "duration": res["duration"],
            "tools": res["tools"],
            "tool_args": res["tool_args"],
            "has_run_query": has_run_query,
            "answer_preview": res["answer"][:180].replace("\n", " "),
            "full_answer": res["answer"],
            "error": res["error"],
        })
    with open("C:/Users/valer/AppData/Local/Temp/opencode/synchrono-api-tests/task2_sql_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("Task 2 finished and saved.")

if __name__ == "__main__":
    run_task2()
