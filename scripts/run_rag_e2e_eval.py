import json
import time
import httpx
import os
import sys
from pathlib import Path

BASE_URL = "http://127.0.0.1:8001"

TEST_DOC_CONTENT = """# SOP Penanganan Insiden Keamanan Data Synchrono 2026
Kode Dokumen: SOP/SYNC/2026/099
Tanggal Berlaku: 27 Oktober 2026

## 1. Definisi dan Ruang Lingkup
Prosedur Operasional Standar ini mengatur tata kelola eskalasi darurat pada platform Synchrono apabila terdeteksi anomali transmisi atau indikasi kebocoran data K/L.

## 2. Tim Penanggung Jawab
Penanggung jawab utama penanganan insiden operasional adalah Tim Tanggap Insiden Siber Synchrono (TTISS).
Email kontak darurat: security-ops@synchrono.go.id

## 3. SLA dan Waktu Tanggap Eskalasi
1. Insiden Level 1 (Kritikal/Paling Parah): Waktu maksimal eskalasi dan notifikasi ke pimpinan adalah 15 menit.
2. Insiden Level 2 (Mayor): Waktu maksimal eskalasi adalah 60 menit.
3. Insiden Level 3 (Minor): Waktu penanganan standar adalah 24 jam kerja.

## 4. Prosedur Pembekuan Akses
Dalam hal terjadi anomali Level 1, TTISS berwenang melakukan isolasi sementara terhadap batch matching yang sedang berjalan tanpa persetujuan manual sebelumnya.
"""

def run_rag_e2e():
    print("=== STARTING SUITE 3: END-TO-END RAG INGESTION LIVE TEST ===")
    
    # Step 1: Create local temporary file
    temp_file = Path("C:/Users/valer/AppData/Local/Temp/opencode/synchrono-api-tests/SOP-Investigasi-Insiden-Data-2026.md")
    temp_file.write_text(TEST_DOC_CONTENT, encoding="utf-8")
    print(f"[1] Staged test document: {temp_file} ({temp_file.stat().st_size} bytes)")
    
    # Step 2: Upload document
    print("[2] Uploading document to POST /api/v1/knowledge/documents ...")
    with open(temp_file, "rb") as f:
        files = {"file": ("SOP-Investigasi-Insiden-Data-2026.md", f, "text/markdown")}
        data = {"source_type": "document"}
        resp = httpx.post(f"{BASE_URL}/api/v1/knowledge/documents", files=files, data=data, timeout=30.0)
        
    print(f"    Upload response: {resp.status_code} -> {resp.text}")
    assert resp.status_code == 202, f"Upload failed: {resp.status_code}"
    upload_res = resp.json()
    doc_id = upload_res["document_id"]
    print(f"    Document ID: {doc_id}, Version: {upload_res.get('version_number')}")
    
    # Step 3: Poll status
    print(f"[3] Polling status for document_id={doc_id} ...")
    status = "queued"
    for i in range(25):
        time.sleep(2)
        stat_resp = httpx.get(f"{BASE_URL}/api/v1/knowledge/documents/{doc_id}", timeout=10.0)
        if stat_resp.status_code == 200:
            stat_data = stat_resp.json()
            status = stat_data.get("status")
            chunk_cnt = stat_data.get("chunk_count")
            print(f"    Check {i+1}: status={status}, chunk_count={chunk_cnt}")
            if status in ("completed", "failed", "superseded"):
                break
                
    assert status == "completed", f"Document processing did not complete: {status}"
    print(f"    Document successfully completed with {chunk_cnt} chunks!")
    
    # Step 4: Check chunks API
    print(f"[4] Verifying chunks API for {doc_id} ...")
    chunks_resp = httpx.get(f"{BASE_URL}/api/v1/knowledge/documents/{doc_id}/chunks", timeout=10.0)
    assert chunks_resp.status_code == 200
    chunks_data = chunks_resp.json()
    print(f"    Retrieved {len(chunks_data.get('chunks', []))} chunks from API.")
    
    # Step 5: Query chatbot on the new knowledge
    time.sleep(2) # brief settle time
    q = "Berdasarkan dokumen SOP investigasi insiden, berapa batas waktu maksimal eskalasi untuk insiden level 1 dan siapa tim penanggung jawabnya?"
    print(f"\n[5] Querying Chatbot with: '{q}' ...")
    
    answer = ""
    t0 = time.time()
    with httpx.stream(
        "POST",
        f"{BASE_URL}/chat",
        json={"user_id": "rag-tester", "thread_id": f"thread-rag-{int(time.time())}", "question": q},
        headers={"Accept": "text/event-stream"},
        timeout=60.0
    ) as chat_resp:
        for line in chat_resp.iter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:].strip())
            if ev.get("step") == "AIMessageChunk" and ev.get("content"):
                answer += ev.get("content")
                
    dur = round(time.time() - t0, 2)
    print(f"\n--- HASIL JAWABAN RAG ({dur}s) ---")
    print(answer)
    
    # Verification
    assert "15 menit" in answer.lower(), "Missing '15 menit' in RAG answer!"
    assert "ttiss" in answer.lower() or "tanggap insiden" in answer.lower(), "Missing TTISS team in RAG answer!"
    print("\n✅ Verification PASSED: Chatbot answered with exact facts from the newly ingested PDF/MD document!")

if __name__ == "__main__":
    run_rag_e2e()
