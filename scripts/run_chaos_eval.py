import asyncio
import json
import time
import httpx

BASE_URL = "http://127.0.0.1:8001/chat"

def test_validation_errors():
    print("[1] Testing Validation & Contract Edge Cases...")
    
    # 1.1 Empty question
    resp = httpx.post(
        BASE_URL,
        json={"user_id": "u1", "thread_id": "t1", "question": ""},
        headers={"Content-Type": "application/json"}
    )
    print(f"    Empty question -> HTTP {resp.status_code} (Expect 422)")
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    
    # 1.2 User ID too long (>36 chars)
    resp = httpx.post(
        BASE_URL,
        json={"user_id": "a" * 37, "thread_id": "t1", "question": "Halo"},
        headers={"Content-Type": "application/json"}
    )
    print(f"    user_id > 36 chars -> HTTP {resp.status_code} (Expect 422)")
    assert resp.status_code == 422
    
    # 1.3 Thread ID too long (>36 chars)
    resp = httpx.post(
        BASE_URL,
        json={"user_id": "u1", "thread_id": "b" * 37, "question": "Halo"},
        headers={"Content-Type": "application/json"}
    )
    print(f"    thread_id > 36 chars -> HTTP {resp.status_code} (Expect 422)")
    assert resp.status_code == 422
    
    # 1.4 Missing required fields
    resp = httpx.post(
        BASE_URL,
        json={"question": "Halo"},
        headers={"Content-Type": "application/json"}
    )
    print(f"    Missing user_id & thread_id -> HTTP {resp.status_code} (Expect 422)")
    assert resp.status_code == 422
    
    print("    [PASS] Validation contracts fail-closed with 422.")

def test_client_early_disconnect():
    print("\n[2] Testing Client Early Disconnect Mid-Stream...")
    # Client connects, reads first 2 lines, then immediately closes socket
    t0 = time.time()
    try:
        with httpx.stream(
            "POST",
            BASE_URL,
            json={"user_id": "disco-user", "thread_id": "disco-thread-1", "question": "Berapa job grading selesai hari ini?"},
            headers={"Accept": "text/event-stream"},
            timeout=10.0
        ) as resp:
            count = 0
            for line in resp.iter_lines():
                count += 1
                if count >= 2:
                    print(f"    Read {count} lines, closing connection abruptly...")
                    break
    except Exception as exc:
        print(f"    Client side closed with: {exc}")
        
    print(f"    Disconnect simulated successfully in {time.time()-t0:.2f}s.")
    # Verify server is still alive
    time.sleep(1)
    health = httpx.get("http://127.0.0.1:8001/api/v1/health")
    print(f"    Post-disconnect health check -> HTTP {health.status_code}: {health.json()}")
    assert health.status_code == 200
    print("    [PASS] Server handled client disconnect gracefully without hang or crash.")

def main():
    print("=== STARTING SUITE 5: CHAOS & RESILIENCE VERIFICATION ===")
    test_validation_errors()
    test_client_early_disconnect()
    print("\nSuite 5 finished successfully.")

if __name__ == "__main__":
    main()
