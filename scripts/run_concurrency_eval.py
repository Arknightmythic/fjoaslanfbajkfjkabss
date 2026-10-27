import asyncio
import json
import time
import httpx

BASE_URL = "http://127.0.0.1:8001/chat"

CONCURRENT_QUESTIONS = [
    {"id": "CC-01", "q": "Berapa job grading selesai hari ini?"},
    {"id": "CC-02", "q": "Berapa total data incoming pemadanan?"},
    {"id": "CC-03", "q": "Apa arti Grade D?"},
    {"id": "CC-04", "q": "Sebutkan nama-nama file yang diunggah Kementerian Kesehatan"},
    {"id": "CC-05", "q": "Berapa batch sinkronisasi yang sudah DONE bulan ini?"},
    {"id": "CC-06", "q": "Berapa jumlah job matching yang berstatus FAILED?"},
    {"id": "CC-07", "q": "Apa kriteria umum Grade A?"},
    {"id": "CC-08", "q": "Berapa jumlah baris data anomali pada data K/L?"},
    {"id": "CC-09", "q": "Berapa total part dari batch yang berstatus DONE?"},
    {"id": "CC-10", "q": "Sebutkan 3 file fisik dengan jumlah baris terbanyak"},
]

async def stream_one(client: httpx.AsyncClient, case: dict) -> dict:
    cid = case["id"]
    q = case["q"]
    t0 = time.time()
    tools = []
    answer = ""
    error = None
    status_code = None
    
    try:
        async with client.stream(
            "POST",
            BASE_URL,
            json={"user_id": f"load-user-{cid}", "thread_id": f"thread-load-{cid}", "question": q},
            headers={"Accept": "text/event-stream"},
            timeout=120.0
        ) as resp:
            status_code = resp.status_code
            if status_code != 200:
                error = f"HTTP {status_code}"
            else:
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        ev = json.loads(line[6:].strip())
                        step = ev.get("step")
                        if step == "AIMessageChunk":
                            if ev.get("tool_calls"):
                                for tc in ev["tool_calls"]:
                                    tools.append(tc.get("name"))
                            elif ev.get("content"):
                                answer += ev.get("content")
                        elif step == "ERROR":
                            error = ev.get("content")
                    except Exception:
                        pass
    except Exception as exc:
        error = str(exc)
        
    dur = round(time.time() - t0, 2)
    return {
        "id": cid,
        "question": q,
        "status_code": status_code,
        "duration": dur,
        "tools": tools,
        "answer_len": len(answer),
        "answer_preview": answer[:100].replace("\n", " "),
        "error": error
    }

async def main():
    print("=== STARTING SUITE 4: 10 CONCURRENT STREAMS LOAD TEST ===")
    t_start = time.time()
    
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=15)
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = [stream_one(client, case) for case in CONCURRENT_QUESTIONS]
        results = await asyncio.gather(*tasks)
        
    t_total = round(time.time() - t_start, 2)
    print(f"\nAll 10 streams finished in total wall-clock time: {t_total}s\n")
    
    success_count = sum(1 for r in results if r["status_code"] == 200 and not r["error"])
    
    for r in results:
        status_sym = "[PASS]" if r["status_code"] == 200 and not r["error"] else "[FAIL]"
        print(f"{status_sym} {r['id']} ({r['duration']}s | Tools: {r['tools']})")
        print(f"      Q: {r['question']}")
        print(f"      Ans ({r['answer_len']} chars): {r['answer_preview']}...")
        if r["error"]:
            print(f"      ERROR: {r['error']}")
        print()
        
    print(f"Concurrency Summary: {success_count}/10 successful responses.")
    assert success_count == 10, f"Expected 10/10 successes, got {success_count}"

if __name__ == "__main__":
    asyncio.run(main())
