"""
FastAPI backend para el CNC Post-Processor.
Endpoints asincrónicos con polling (job_id) para evitar timeout en traducciones largas.
"""
from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import settings, load_llm_config, save_llm_config
from pipeline.graph import run_translation


# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CNC Post-Processor",
    description="Traduce G-code Fanuc a Siemens 840D con validación geométrica.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ThreadPoolExecutor para correr el pipeline (sincrónico) sin bloquear el event loop
_executor = ThreadPoolExecutor(max_workers=4)


# ─── Modelos de respuesta ─────────────────────────────────────────────────────

class JobStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    DONE      = "done"
    ERROR     = "error"


class JobResponse(BaseModel):
    job_id:  str
    status:  JobStatus
    message: str = ""


class TranslationResult(BaseModel):
    job_id:              str
    status:              JobStatus
    success:             bool
    translated_code:     str
    source_toolpath:     List[List[float]]   # [[x, y, z], ...]
    translated_toolpath: List[List[float]]
    deviation_points:    List[int]
    max_deviation_mm:    float
    avg_deviation_mm:    float
    confidence:          float
    confidence_label:    str
    attempts_used:       int
    warnings:            List[str]
    errors:              List[str]


class LLMConfig(BaseModel):
    provider:   str
    model:      str
    temperature: float
    max_tokens: int
    timeout_seconds: int
    available_providers: Optional[List[Dict[str, Any]]] = None


class HealthResponse(BaseModel):
    status:   str
    version:  str
    provider: str
    model:    str


# ─── Almacén en memoria de jobs ───────────────────────────────────────────────

_jobs: Dict[str, Dict[str, Any]] = {}


def _run_pipeline_sync(job_id: str, source_code: str) -> None:
    """Ejecuta el pipeline en un thread y actualiza el estado del job."""
    try:
        _jobs[job_id]["status"] = JobStatus.RUNNING
        result = run_translation(source_code, max_attempts=settings.max_correction_attempts)
        _jobs[job_id].update({
            "status": JobStatus.DONE,
            "result": result,
        })
    except Exception as exc:
        _jobs[job_id].update({
            "status": JobStatus.ERROR,
            "error": str(exc),
        })


def _point3d_to_list(points: list) -> List[List[float]]:
    """Convierte lista de Point3D (tuple o list) a [[x,y,z], ...]."""
    return [[float(p[0]), float(p[1]), float(p[2])] for p in points]


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    cfg = load_llm_config()
    return HealthResponse(
        status="ok",
        version="1.0.0",
        provider=cfg.get("provider", "openai"),
        model=cfg.get("model", "gpt-4o"),
    )


@app.post("/api/translate", response_model=JobResponse, status_code=202)
async def translate(file: UploadFile = File(...)) -> JobResponse:
    """
    Acepta un archivo .nc/.mpf/.txt Fanuc y lanza la traducción en background.
    Retorna job_id para hacer polling en GET /api/jobs/{job_id}.
    """
    # Validar tamaño
    content = await file.read()
    size_kb = len(content) / 1024
    if size_kb > settings.max_file_size_kb:
        raise HTTPException(
            status_code=413,
            detail=f"Archivo demasiado grande ({size_kb:.1f}KB). Máximo: {settings.max_file_size_kb}KB",
        )

    # Validar encoding
    try:
        source_code = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            source_code = content.decode("latin-1")
        except Exception:
            raise HTTPException(status_code=400, detail="No se pudo decodificar el archivo.")

    if not source_code.strip():
        raise HTTPException(status_code=400, detail="El archivo está vacío.")

    # Crear job
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": JobStatus.PENDING, "result": None, "error": None}

    # Lanzar en background (thread pool, no bloquea el event loop)
    loop = asyncio.get_event_loop()
    loop.run_in_executor(_executor, _run_pipeline_sync, job_id, source_code)

    return JobResponse(job_id=job_id, status=JobStatus.PENDING, message="Traducción iniciada.")


@app.get("/api/jobs/{job_id}", response_model=TranslationResult)
async def get_job(job_id: str) -> TranslationResult:
    """Polling endpoint. Retorna estado y resultado cuando status=done."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' no encontrado.")

    status = job["status"]

    if status == JobStatus.ERROR:
        return TranslationResult(
            job_id=job_id,
            status=status,
            success=False,
            translated_code="",
            source_toolpath=[],
            translated_toolpath=[],
            deviation_points=[],
            max_deviation_mm=0.0,
            avg_deviation_mm=0.0,
            confidence=0.0,
            confidence_label="MUY BAJA",
            attempts_used=0,
            warnings=[],
            errors=[job.get("error", "Error desconocido.")],
        )

    if status in (JobStatus.PENDING, JobStatus.RUNNING):
        return TranslationResult(
            job_id=job_id,
            status=status,
            success=False,
            translated_code="",
            source_toolpath=[],
            translated_toolpath=[],
            deviation_points=[],
            max_deviation_mm=0.0,
            avg_deviation_mm=0.0,
            confidence=0.0,
            confidence_label="",
            attempts_used=0,
            warnings=[],
            errors=[],
        )

    # DONE
    result = job["result"]
    return TranslationResult(
        job_id=job_id,
        status=status,
        success=result["success"],
        translated_code=result["translated_code"],
        source_toolpath=_point3d_to_list(result["source_toolpath"]),
        translated_toolpath=_point3d_to_list(result["translated_toolpath"]),
        deviation_points=result["deviation_points"],
        max_deviation_mm=result["max_deviation_mm"],
        avg_deviation_mm=result["avg_deviation_mm"],
        confidence=result["confidence"],
        confidence_label=result["confidence_label"],
        attempts_used=result["attempts_used"],
        warnings=result["warnings"],
        errors=result["errors"],
    )


@app.get("/api/config", response_model=LLMConfig)
async def get_config() -> LLMConfig:
    """Retorna la configuración actual del LLM."""
    cfg = load_llm_config()
    return LLMConfig(
        provider=cfg.get("provider", "openai"),
        model=cfg.get("model", "gpt-4o"),
        temperature=cfg.get("temperature", 0.1),
        max_tokens=cfg.get("max_tokens", 2048),
        timeout_seconds=cfg.get("timeout_seconds", 30),
        available_providers=cfg.get("available_providers"),
    )


@app.put("/api/config", response_model=LLMConfig)
async def update_config(new_config: LLMConfig) -> LLMConfig:
    """Actualiza la configuración del LLM en llm_config.json."""
    current = load_llm_config()

    # Actualizar solo los campos enviados
    current.update({
        "provider":    new_config.provider,
        "model":       new_config.model,
        "temperature": new_config.temperature,
        "max_tokens":  new_config.max_tokens,
        "timeout_seconds": new_config.timeout_seconds,
    })

    save_llm_config(current)
    return new_config
