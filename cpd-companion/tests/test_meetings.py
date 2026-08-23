import os

from tests.test_app import KEY, client, login  # noqa: F401 - reuse env setup + fixture
from app import db


def test_meeting_pipeline_end_to_end(client):  # noqa: F811
    login(client)

    # upload a recording (fake bytes are fine — transcription happens on the host)
    r = client.post(
        "/meetings/upload",
        data={
            "meeting_type": "mm_meeting",
            "date": "2026-08-01",
            "participants": "Dr B (geriatrician)",
            "duration_minutes": "45",
            "notes": "",
            "consent": "yes",
        },
        files={"audio": ("mm-aug.m4a", b"fake-audio-bytes", "audio/mp4")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "whisper"}).json()
    whisper_job = [j for j in jobs if j["kind"] == "transcribe_meeting"][-1]
    assert whisper_job["payload"]["meeting_type"] == "mm_meeting"

    # whisper drain posts the transcript -> claude summary job is spawned
    r = client.post(f"/api/jobs/{whisper_job['id']}/result", headers=KEY,
                    json={"transcript": "We reviewed the fall of an admitted patient."})
    assert r.status_code == 200
    summary_job_id = r.json()["summary_job_id"]

    claude_jobs = client.get("/api/jobs", headers=KEY, params={"engine": "claude"}).json()
    job = [j for j in claude_jobs if j["id"] == summary_job_id][0]
    assert "transcript" in job["payload"]
    assert "de-identify" in job["prompt"].lower()

    # claude drain posts minutes -> draft Cat 3 activity with evidence
    r = client.post(f"/api/jobs/{summary_job_id}/result", headers=KEY, json={
        "title": "Practice outcomes meeting — August",
        "summary_md": "## Topics\n- fall review",
        "reflection": "We will change X.",
    })
    assert r.status_code == 200
    activity_id = r.json()["draft_activity_id"]

    drafts = client.get("/api/activities", headers=KEY, params={"status": "draft"}).json()
    draft = [a for a in drafts if a["id"] == activity_id][0]
    assert draft["category"] == 3
    assert draft["minutes"] == 45
    assert draft["source_module"] == "meetings"

    # double-posting the same job is rejected
    r = client.post(f"/api/jobs/{summary_job_id}/result", headers=KEY, json={
        "title": "x", "summary_md": "y", "reflection": "",
    })
    assert r.status_code == 422

    # evidence files exist on disk
    data_dir = os.environ["CPD_DATA_DIR"]
    evidence_files = os.listdir(os.path.join(data_dir, "evidence"))
    assert any(f.startswith(f"meeting_{summary_job_id}") for f in evidence_files)

    # the transcript is scrubbed from the completed job's payload
    with db.tx() as conn:
        done_job = conn.execute("SELECT * FROM jobs WHERE id = ?",
                                (summary_job_id,)).fetchone()
    assert "We reviewed the fall" not in (done_job["payload"] or "")


def test_job_fail_path_retries_then_gives_up(client):  # noqa: F811
    login(client)
    r = client.post(
        "/meetings/upload",
        data={"meeting_type": "peer_discussion", "date": "2026-08-02",
              "participants": "", "duration_minutes": "10", "notes": "", "consent": "yes"},
        files={"audio": ("chat.mp3", b"bytes", "audio/mpeg")},
        follow_redirects=False,
    )
    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "whisper"}).json()
    jid = jobs[-1]["id"]
    r = client.post(f"/api/jobs/{jid}/fail", headers=KEY, json={"error": "no GPU today"})
    assert r.json()["status"] == "failed"
    assert client.post(f"/api/jobs/{jid}/fail", headers=KEY, json={"error": "again"}).status_code == 422

    # the audio file survives, so the failure re-queues a retry (capped at 2)
    retry1 = r.json()["requeued_job_id"]
    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "whisper"}).json()
    job1 = next(j for j in jobs if j["id"] == retry1)
    assert job1["payload"]["retries"] == 1
    r = client.post(f"/api/jobs/{retry1}/fail", headers=KEY, json={"error": "still no GPU"})
    retry2 = r.json()["requeued_job_id"]
    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "whisper"}).json()
    assert next(j for j in jobs if j["id"] == retry2)["payload"]["retries"] == 2
    r = client.post(f"/api/jobs/{retry2}/fail", headers=KEY, json={"error": "give up"})
    assert "requeued_job_id" not in r.json()  # retry cap reached
    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "whisper"}).json()
    assert not any(j["kind"] == "transcribe_meeting"
                   and j["payload"].get("audio_file") == job1["payload"]["audio_file"]
                   for j in jobs)
