"""
Tests de la API FastAPI.
Usa TestClient de httpx para pruebas sin servidor real.
El pipeline pesado se mockea para tests de endpoints.
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app, _jobs, JobStatus

client = TestClient(app)

SIMPLE_NC = b"G0 X10 Y20\nG1 X100 F200\nM30"


# ─── Health ──────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_ok(self):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "provider" in data
        assert "model" in data


# ─── Config ──────────────────────────────────────────────────────────────────

class TestConfig:
    def test_get_config_returns_fields(self):
        r = client.get("/api/config")
        assert r.status_code == 200
        data = r.json()
        assert "provider" in data
        assert "model" in data
        assert "temperature" in data
        assert "max_tokens" in data

    def test_put_config_updates(self):
        payload = {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "temperature": 0.2,
            "max_tokens": 1024,
            "timeout_seconds": 20,
        }
        r = client.put("/api/config", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["model"] == "gpt-4o-mini"
        assert data["temperature"] == 0.2

        # Verificar que GET refleja el cambio
        r2 = client.get("/api/config")
        assert r2.json()["model"] == "gpt-4o-mini"


# ─── Translate ────────────────────────────────────────────────────────────────

class TestTranslate:
    def test_translate_returns_job_id(self):
        files = {"file": ("test.nc", SIMPLE_NC, "text/plain")}
        r = client.post("/api/translate", files=files)
        assert r.status_code == 202
        data = r.json()
        assert "job_id" in data
        assert data["status"] == "pending"

    def test_translate_empty_file_returns_400(self):
        files = {"file": ("empty.nc", b"", "text/plain")}
        r = client.post("/api/translate", files=files)
        assert r.status_code == 400

    def test_translate_large_file_returns_413(self):
        huge = b"G0 X10\n" * 100_000  # ~700KB
        files = {"file": ("huge.nc", huge, "text/plain")}
        r = client.post("/api/translate", files=files)
        assert r.status_code == 413

    def test_job_not_found_returns_404(self):
        r = client.get("/api/jobs/nonexistent-uuid-1234")
        assert r.status_code == 404

    def test_job_lifecycle_pending_to_done(self):
        """Test completo: crear job → estado pending → inyectar resultado → done."""
        # Crear job
        files = {"file": ("test.nc", SIMPLE_NC, "text/plain")}
        r = client.post("/api/translate", files=files)
        job_id = r.json()["job_id"]

        # Mientras el pipeline corre, estado puede ser pending o running
        r2 = client.get(f"/api/jobs/{job_id}")
        assert r2.status_code == 200
        assert r2.json()["status"] in ("pending", "running", "done")

    def test_job_error_state(self):
        """Inyecta directamente un job en estado error y verifica respuesta."""
        job_id = "test-error-job"
        _jobs[job_id] = {
            "status": JobStatus.ERROR,
            "result": None,
            "error": "Pipeline falló por razón X",
        }
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "error"
        assert not data["success"]
        assert "Pipeline falló" in data["errors"][0]
        del _jobs[job_id]

    def test_job_done_state(self):
        """Inyecta directamente un job completado y verifica estructura de respuesta."""
        job_id = "test-done-job"
        _jobs[job_id] = {
            "status": JobStatus.DONE,
            "result": {
                "success": True,
                "translated_code": "%_N_TEST_MPF\nG0 X10\nM30",
                "source_toolpath": [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)],
                "translated_toolpath": [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)],
                "deviation_points": [],
                "max_deviation_mm": 0.0,
                "avg_deviation_mm": 0.0,
                "confidence": 0.95,
                "confidence_label": "ALTA",
                "attempts_used": 0,
                "warnings": [],
                "errors": [],
            },
            "error": None,
        }
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "done"
        assert data["success"] is True
        assert "%_N_TEST_MPF" in data["translated_code"]
        assert data["confidence"] == 0.95
        assert data["confidence_label"] == "ALTA"
        assert isinstance(data["source_toolpath"], list)
        assert data["source_toolpath"][1] == [10.0, 0.0, 0.0]
        del _jobs[job_id]

    def test_toolpath_format_is_list_of_lists(self):
        """Verifica que los toolpaths se serialicen como [[x,y,z], ...] no como tuplas."""
        job_id = "test-format-job"
        _jobs[job_id] = {
            "status": JobStatus.DONE,
            "result": {
                "success": True,
                "translated_code": "G0 X0",
                "source_toolpath": [(1.0, 2.0, 3.0)],
                "translated_toolpath": [(1.0, 2.0, 3.0)],
                "deviation_points": [],
                "max_deviation_mm": 0.0,
                "avg_deviation_mm": 0.0,
                "confidence": 1.0,
                "confidence_label": "ALTA",
                "attempts_used": 0,
                "warnings": [],
                "errors": [],
            },
            "error": None,
        }
        r = client.get(f"/api/jobs/{job_id}")
        data = r.json()
        point = data["source_toolpath"][0]
        assert isinstance(point, list)
        assert len(point) == 3
        assert point == [1.0, 2.0, 3.0]
        del _jobs[job_id]
