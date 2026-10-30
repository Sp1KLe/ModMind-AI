from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

MODRINTH_API = "https://api.modrinth.com/v2"
USER_AGENT = "ModMindAI/0.1.0 (https://github.com/Sp1KLe/ModMind-AI)"
MAX_DOWNLOAD_BYTES = 450 * 1024 * 1024
ALLOWED_DOWNLOAD_HOSTS = {"cdn.modrinth.com"}

app = FastAPI(title="ModMind AI", version="0.1.0", description="Free Minecraft modpack builder")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict this to your app domain before production.
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
    facets = [
        ["project_type:mod"],
        [f"versions:{minecraft_version}"],
        [f"categories:{loader}"],
    ]
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            data = await api_get(client, "/search", {
                "query": query,
                "facets": __import__("json").dumps(facets),
                "limit": limit,
            })
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"Modrinth search failed: {exc}") from exc

    hits = []
    for item in data.get("hits", []):
        hits.append({
            "id": item.get("project_id"),
            "slug": item.get("slug"),
            "title": item.get("title"),
            "description": item.get("description"),
            "icon_url": item.get("icon_url"),
            "downloads": item.get("downloads"),
            "categories": item.get("categories", []),
            "project_url": f"https://modrinth.com/mod/{item.get('slug')}",
        })
    return {"total_hits": data.get("total_hits", 0), "mods": hits}


@app.post("/api/build")
async def build_pack(request: BuildRequest):
    project_ids = list(dict.fromkeys(request.project_ids))
    if len(project_ids) > 40:
        raise HTTPException(400, "Maximum 40 mods per pack")

    files_to_download: list[tuple[str, str]] = []
    total_bytes = 0
    manifest_mods = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=15), follow_redirects=True) as client:
            for project_id in project_ids:
                versions = await api_get(client, f"/project/{project_id}/version", {
                    "game_versions": f'["{request.minecraft_version}"]',
                    "loaders": f'["{request.loader}"]',
                })
                if not versions:
                    raise HTTPException(422, f"No compatible version found for {project_id}")
                version = versions[0]
                primary = next((f for f in version.get("files", []) if f.get("primary")), None)
                if primary is None and version.get("files"):
                    primary = version["files"][0]
                if not primary:
                    raise HTTPException(422, f"No downloadable file for {project_id}")

                for dep in version.get("dependencies", []):
                    if dep.get("dependency_type") == "required" and dep.get("project_id") not in project_ids:
                        raise HTTPException(
                            422,
                            f"Missing required dependency for {project_id}: {dep.get('project_id')}. Add it to the selected mods and retry.",
                        )

                url = primary.get("url", "")
                host = urlparse(url).hostname
                if urlparse(url).scheme != "https" or host not in ALLOWED_DOWNLOAD_HOSTS:
                    raise HTTPException(422, f"Unexpected download host for {project_id}")
                files_to_download.append((primary.get("filename") or f"{project_id}.jar", url))
                manifest_mods.append({
                    "project_id": project_id,
                    "name": version.get("name"),
                    "version_number": version.get("version_number"),
                    "filename": primary.get("filename"),
                    "download_url": url,
                })

            with tempfile.TemporaryDirectory(prefix="modmind-") as temp_dir:
                archive_path = Path(temp_dir) / "modmind-pack.zip"
                with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("manifest.json", __import__("json").dumps({
                        "name": clean_name(request.name),
                        "minecraft_version": request.minecraft_version,
                        "loader": request.loader,
                        "mods": manifest_mods,
                    }, ensure_ascii=False, indent=2))
                    for filename, url in files_to_download:
                        response = await client.get(url)
                        response.raise_for_status()
                        total_bytes += len(response.content)
                        if total_bytes > MAX_DOWNLOAD_BYTES:
                            raise HTTPException(413, "Pack exceeds the 450 MB server build limit")
                        safe_filename = Path(filename).name
                        archive.writestr(f"mods/{safe_filename}", response.content)

                # FileResponse needs a persistent path, so move the archive to a short-lived temp file.
                persistent = Path(tempfile.gettempdir()) / f"modmind-{next(tempfile._get_candidate_names())}.zip"
                persistent.write_bytes(archive_path.read_bytes())

    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(502, f"Could not build modpack: {exc}") from exc

    return FileResponse(
        persistent,
        media_type="application/zip",
        filename=f"{clean_name(request.name)}.zip",
        background=None,
    )


if Path("web").exists():
    app.mount("/", StaticFiles(directory="web", html=True), name="web")
