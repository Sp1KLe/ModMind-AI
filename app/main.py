from __future__ import annotations

import json
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

MODRINTH_API = "https://api.modrinth.com/v2"
USER_AGENT = "ModMindAI/0.2.0 (https://github.com/Sp1KLe/ModMind-AI)"
MAX_DOWNLOAD_BYTES = 450 * 1024 * 1024
MAX_PROJECTS = 80
ALLOWED_DOWNLOAD_HOSTS = {"cdn.modrinth.com"}
LOADERS = {"fabric", "forge", "neoforge", "quilt"}

app = FastAPI(title="ModMind AI", version="0.2.0", description="Free Minecraft modpack builder")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict this to the app domain before production.
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class BuildRequest(BaseModel):
    name: str = Field(default="ModMind Pack", min_length=1, max_length=64)
    minecraft_version: str = Field(min_length=1, max_length=24)
    loader: str = Field(pattern="^(fabric|forge|neoforge|quilt)$")
    project_ids: list[str] = Field(min_length=1, max_length=40)


def clean_name(value: str) -> str:
    value = re.sub(r"[^\w .-]", "", value, flags=re.UNICODE).strip()
    return (value or "ModMind Pack")[:64]


def modrinth_headers() -> dict[str, str]:
    return {"User-Agent": USER_AGENT}


async def api_get(client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None):
    response = await client.get(f"{MODRINTH_API}{path}", params=params, headers=modrinth_headers())
    response.raise_for_status()
    return response.json()


@app.get("/api/health")
async def health():
    return {"ok": True, "app": "ModMind AI", "version": app.version}


@app.get("/api/search")
async def search_mods(
    query: str = Query(min_length=1, max_length=120),
    minecraft_version: str = Query(min_length=1, max_length=24),
    loader: str = Query(pattern="^(fabric|forge|neoforge|quilt)$"),
    limit: int = Query(default=12, ge=1, le=30),
):
    facets = [["project_type:mod"], [f"versions:{minecraft_version}"], [f"categories:{loader}"]]
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            data = await api_get(client, "/search", {
                "query": query,
                "facets": json.dumps(facets),
                "limit": limit,
            })
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"Modrinth search failed: {exc}") from exc

    mods = []
    for item in data.get("hits", []):
        mods.append({
            "id": item.get("project_id"),
            "slug": item.get("slug"),
            "title": item.get("title"),
            "description": item.get("description"),
            "icon_url": item.get("icon_url"),
            "downloads": item.get("downloads"),
            "categories": item.get("categories", []),
            "project_url": f"https://modrinth.com/mod/{item.get('slug')}",
        })
    return {"total_hits": data.get("total_hits", 0), "mods": mods}


async def compatible_version(client: httpx.AsyncClient, project_id: str, game_version: str, loader: str):
    versions = await api_get(client, f"/project/{project_id}/version", {
        "game_versions": json.dumps([game_version]),
        "loaders": json.dumps([loader]),
    })
    if not versions:
        raise HTTPException(422, f"No compatible version found for {project_id}")
    return versions[0]


def primary_file(version: dict[str, Any], project_id: str) -> dict[str, Any]:
    files = version.get("files") or []
    selected = next((item for item in files if item.get("primary")), None)
    if selected is None and files:
        selected = files[0]
    if not selected or not selected.get("url"):
        raise HTTPException(422, f"No downloadable file for {project_id}")
    parsed = urlparse(selected["url"])
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
        raise HTTPException(422, f"Unexpected download host for {project_id}")
    return selected


@app.post("/api/build")
async def build_pack(request: BuildRequest):
    selected_ids = list(dict.fromkeys(request.project_ids))
    included: dict[str, dict[str, Any]] = {}
    pending = list(selected_ids)
    total_bytes = 0
    manifest_mods: list[dict[str, Any]] = []
    archive_path: Path | None = None

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(45, connect=15),
            follow_redirects=True,
        ) as client:
            # Resolve required dependencies recursively instead of making users add them manually.
            while pending:
                project_id = pending.pop(0)
                if project_id in included:
                    continue
                if len(included) >= MAX_PROJECTS:
                    raise HTTPException(413, f"Modpack needs more than {MAX_PROJECTS} projects; reduce your selection.")

                version = await compatible_version(client, project_id, request.minecraft_version, request.loader)
                selected_file = primary_file(version, project_id)
                included[project_id] = {"version": version, "file": selected_file}

                for dependency in version.get("dependencies", []):
                    if dependency.get("dependency_type") != "required":
                        continue
                    dependency_project = dependency.get("project_id")
                    dependency_version = dependency.get("version_id")
                    if not dependency_project and dependency_version:
                        version_info = await api_get(client, f"/version/{dependency_version}")
                        dependency_project = version_info.get("project_id")
                    if dependency_project and dependency_project not in included and dependency_project not in pending:
                        pending.append(dependency_project)

            with tempfile.TemporaryDirectory(prefix="modmind-") as temp_dir:
                archive_path = Path(temp_dir) / "modmind-pack.zip"
                used_names: set[str] = set()
                with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for project_id, item in included.items():
                        version = item["version"]
                        file_info = item["file"]
                        filename = Path(file_info.get("filename") or f"{project_id}.jar").name
                        stem, suffix = Path(filename).stem, Path(filename).suffix
                        safe_filename = filename
                        counter = 2
                        while safe_filename.lower() in used_names:
                            safe_filename = f"{stem}-{counter}{suffix}"
                            counter += 1
                        used_names.add(safe_filename.lower())

                        async with client.stream("GET", file_info["url"], headers=modrinth_headers()) as response:
                            response.raise_for_status()
                            chunks = []
                            async for chunk in response.aiter_bytes():
                                total_bytes += len(chunk)
                                if total_bytes > MAX_DOWNLOAD_BYTES:
                                    raise HTTPException(413, "Pack exceeds the 450 MB server build limit.")
                                chunks.append(chunk)
                        archive.writestr(f"mods/{safe_filename}", b"".join(chunks))
                        manifest_mods.append({
                            "project_id": project_id,
                            "name": version.get("name"),
                            "version_number": version.get("version_number"),
                            "filename": safe_filename,
                            "download_url": file_info["url"],
                            "automatically_added": project_id not in selected_ids,
                        })

                    archive.writestr("manifest.json", json.dumps({
                        "format": "ModMind ZIP",
                        "format_version": 1,
                        "name": clean_name(request.name),
                        "minecraft_version": request.minecraft_version,
                        "loader": request.loader,
                        "selected_projects": selected_ids,
                        "mods": manifest_mods,
                    }, ensure_ascii=False, indent=2))

                final_path = Path(tempfile.gettempdir()) / f"modmind-{uuid4().hex}.zip"
                final_path.write_bytes(archive_path.read_bytes())

    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(502, f"Could not build modpack: {exc}") from exc

    return FileResponse(
        final_path,
        media_type="application/zip",
        filename=f"{clean_name(request.name)}.zip",
        background=BackgroundTask(final_path.unlink, missing_ok=True),
    )


if Path("web").exists():
    app.mount("/", StaticFiles(directory="web", html=True), name="web")
