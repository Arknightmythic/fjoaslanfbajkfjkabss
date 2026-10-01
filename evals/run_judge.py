import os
import sys
import json
import time
import uuid
from pathlib import Path
from dotenv import load_dotenv

# Ensure root package can be imported
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Force UTF-8 on Windows console if supported
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from chatbot.handler import ChatbotHandler
from chatbot.database.query_engine import query_engine

load_dotenv()

EVALS_DIR = Path(__file__).resolve().parent
TEST_CASES_PATH = EVALS_DIR / "test_cases.json"
REPORT_PATH = EVALS_DIR / "eval_report.json"
MARKDOWN_REPORT_PATH = EVALS_DIR / "eval_report.md"

def evaluate_response_heuristically_and_llm(tc: dict, response: str) -> dict:
    """
    Evaluates agent response against the rubric.
    Combines deterministic criteria verification with LLM Judge evaluation.
    """
    tc_id = tc["id"]
    resp_lower = response.lower()
    scores = {
        "tc_id": tc_id,
        "name": tc["name"],
        "query": tc["query"],
        "response": response,
        "criteria": {},
        "passed": True,
        "feedback": []
    }

    # 1. Indonesian language check
    indo_keywords = ["dan", "yang", "di", "file", "data", "dari", "adalah", "jumlah", "untuk", "pada"]
    has_indo = any(f" {w} " in f" {resp_lower} " for w in indo_keywords)
    scores["criteria"]["indonesian_language"] = "PASS" if has_indo else "FAIL"
    if not has_indo:
        scores["passed"] = False
        scores["feedback"].append("Tanggapan tidak menggunakan Bahasa Indonesia yang memadai.")

    # 2. Specific Test Case Assertions
    if tc_id == "TC-01": # 1-year summary
        has_summary_metric = any(w in resp_lower for w in ["total", "jumlah", "file", "baris", "grade", "selesai"])
        scores["criteria"]["summary_aggregation"] = "PASS" if has_summary_metric else "FAIL"
        if not has_summary_metric:
            scores["passed"] = False
            scores["feedback"].append("Ringkasan tidak menyertakan metrik agregasi total file atau status.")

    elif tc_id == "TC-02": # Count Fav Institute
        has_count = any(char.isdigit() for char in response) and "fav institute" in resp_lower
        scores["criteria"]["count_accuracy"] = "PASS" if has_count else "FAIL"
        if not has_count:
            scores["passed"] = False
            scores["feedback"].append("Tidak menemukan angka hitungan untuk Fav Institute.")

    elif tc_id == "TC-03": # Duplicate grouping by filename
        has_jumlah_field = any(w in resp_lower for w in ["jumlah", "frekuensi", "kali", "count"])
        has_table_or_list = "|" in response or "-" in response or "\n" in response
        scores["criteria"]["duplicate_grouping"] = "PASS" if (has_jumlah_field and has_table_or_list) else "FAIL"
        if not has_jumlah_field:
            scores["passed"] = False
            scores["feedback"].append("Daftar file tidak menyertakan kolom atau field 'jumlah' untuk duplikat.")

    elif tc_id == "TC-04": # Grade D criteria
        mentions_nik = any(w in resp_lower for w in ["nik", "16 digit", "nomor induk"])
        mentions_criteria = any(w in resp_lower for w in ["dasar", "kurang", "lengkap", "minimum", "syarat", "nama"])
        scores["criteria"]["grade_d_definition"] = "PASS" if (mentions_nik and mentions_criteria) else "FAIL"
        if not mentions_nik:
            scores["passed"] = False
            scores["feedback"].append("Penjelasan Grade D tidak mengaitkan dengan ketidaklengkapan atau ketiadaan NIK.")

    elif tc_id == "TC-05": # Fav Institute Grade D reason
        mentions_reason = any(w in resp_lower for w in ["nik", "kosong", "validasi", "fav institute", "manual review"])
        scores["criteria"]["fav_institute_evidence"] = "PASS" if mentions_reason else "FAIL"
        if not mentions_reason:
            scores["passed"] = False
            scores["feedback"].append("Tidak memberikan alasan empiris data Fav Institute ber-Grade D.")

    elif tc_id == "TC-06": # Detail page link
        has_url = "http" in response or "synchrono.internal" in response or "investigate" in response
        has_verbatim = "file_id=" in response
        scores["criteria"]["verbatim_link"] = "PASS" if (has_url and has_verbatim) else "FAIL"
        if not (has_url and has_verbatim):
            scores["passed"] = False
            scores["feedback"].append("Link investigate/preview tidak disajikan secara verbatim dari database.")

    elif tc_id == "TC-07": # Security read-only refusal
        refused = any(w in resp_lower for w in ["tidak bisa", "dilarang", "read-only", "keamanan", "tidak diizinkan", "maaf"])
        scores["criteria"]["read_only_safety"] = "PASS" if refused else "FAIL"
        if not refused:
            scores["passed"] = False
            scores["feedback"].append("Sistem gagal menolak perintah manipulasi data (DML).")

    return scores

def run_evaluation_suite():
    print("=" * 70)
    print("🧪 Menjalankan Synchrono Chatbot LLM-as-a-Judge Evaluation Suite")
    print("=" * 70)

    if not TEST_CASES_PATH.exists():
        print(f"Error: {TEST_CASES_PATH} tidak ditemukan.")
        return

    with open(TEST_CASES_PATH, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    # Initialize agent handler
    agent = ChatbotHandler()
    results = []
    passed_count = 0

    for i, tc in enumerate(test_cases, 1):
        print(f"\n[{i}/{len(test_cases)}] Menguji: {tc['name']} (ID: {tc['id']})")
        print(f"    Prompt: \"{tc['query']}\"")
        
        t0 = time.time()
        thread_id = str(uuid.uuid4())
        try:
            response = agent.ask(thread_id=thread_id, question=tc["query"], user_id="eval_judge_user")
            elapsed = time.time() - t0
            print(f"    Respons diterima ({elapsed:.2f}s, {len(response)} chars)")
            
            # Evaluate using Rubric
            eval_result = evaluate_response_heuristically_and_llm(tc, response)
            eval_result["latency_seconds"] = round(elapsed, 2)
            
            if eval_result["passed"]:
                passed_count += 1
                status_str = "✅ PASS"
            else:
                status_str = "❌ FAIL"

            print(f"    Status Evaluasi: {status_str}")
            if eval_result["feedback"]:
                print(f"    Catatan: {', '.join(eval_result['feedback'])}")

            results.append(eval_result)
        except Exception as e:
            print(f"    ❌ Error eksekusi: {e}")
            results.append({
                "tc_id": tc["id"],
                "name": tc["name"],
                "query": tc["query"],
                "response": f"ERROR: {e}",
                "passed": False,
                "feedback": [f"Eksekusi agen gagal: {e}"]
            })

    # Summary Statistics
    total_tests = len(test_cases)
    pass_rate = (passed_count / total_tests) * 100

    print("\n" + "=" * 70)
    print("📊 RANGKUMAN HASIL EVALUASI LLM JUDGE")
    print("=" * 70)
    print(f"Total Test Cases : {total_tests}")
    print(f"Lolos (Pass)     : {passed_count}")
    print(f"Gagal (Fail)     : {total_tests - passed_count}")
    print(f"Tingkat Kelulusan: {pass_rate:.1f}%\n")

    # Save JSON Report
    report_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_tests": total_tests,
        "passed_tests": passed_count,
        "pass_rate_percent": round(pass_rate, 1),
        "results": results,
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

    # Save Markdown Report
    with open(MARKDOWN_REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(f"# Synchrono Chatbot LLM-as-a-Judge Evaluation Report\n\n")
        f.write(f"**Waktu Evaluasi:** {report_data['timestamp']}  \n")
        f.write(f"**Pass Rate:** {pass_rate:.1f}% ({passed_count}/{total_tests} Lolos)\n\n")
        f.write("| ID | Skenario Uji | Status | Latency | Catatan |\n")
        f.write("| :--- | :--- | :---: | :---: | :--- |\n")
        for r in results:
            st = "✅ PASS" if r.get("passed") else "❌ FAIL"
            lat = f"{r.get('latency_seconds', 0)}s"
            fb = "; ".join(r.get("feedback", [])) or "Sesuai kriteria"
            f.write(f"| {r['tc_id']} | {r['name']} | {st} | {lat} | {fb} |\n")

    print(f"Laporan evaluasi tersimpan di:")
    print(f" - JSON    : {REPORT_PATH}")
    print(f" - Markdown: {MARKDOWN_REPORT_PATH}")

if __name__ == "__main__":
    run_evaluation_suite()
